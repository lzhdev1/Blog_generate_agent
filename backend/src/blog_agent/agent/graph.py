import json
from typing import List, Optional

from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, END

from src.blog_agent.agent.state import AgentState
from src.blog_agent.agent.agents import (
    ResearcherAgent,
    TitleAgent,
    OutlinerAgent,
    WriterAgent,
    ReviewerAgent,
    ImageAgent,
)
from src.blog_agent.agent.agents.formatter import format_markdown
from src.blog_agent.service.task_service import TaskService
from src.blog_agent.db.models import TaskStatus
from config.settings import settings

# 初始化各个 Agent
researcher = ResearcherAgent()
title_agent = TitleAgent()
outliner = OutlinerAgent()
writer = WriterAgent()
reviewer = ReviewerAgent()
image_agent = ImageAgent()


# ============================================================
# 阶段1：标题调研 + 生成标题
# ============================================================

def run_generate_titles(db: Session, task_id: int, topic: str) -> List[str]:
    """
    阶段1：标题调研 → 生成标题
    用 LangGraph 编排
    """
    TaskService.update_status(db, task_id, TaskStatus.RESEARCHING_TITLE)

    # 定义节点函数（闭包访问 db）
    def research_node(state: AgentState) -> AgentState:
        TaskService.update_progress(db, task_id, "正在分析同类文章标题...")
        research = researcher.research_for_titles(topic)
        TaskService.save_title_research(db, task_id, research)
        return {**state, "title_research": research}

    def generate_titles_node(state: AgentState) -> AgentState:
        TaskService.update_status(db, task_id, TaskStatus.GENERATING_TITLES)
        TaskService.update_progress(db, task_id, "正在生成标题...")
        titles = title_agent.generate_titles(topic, state["title_research"])
        return {**state, "titles": titles}

    def score_titles_node(state: AgentState) -> AgentState:
        TaskService.update_progress(db, task_id, "正在评估标题质量...")
        scores = researcher.score_titles(topic, state["titles"], state["title_research"])
        # 标题和评分一次性保存，避免竞态：前端轮询时标题存在但评分为空的窗口
        TaskService.save_titles(db, task_id, state["titles"], scores)
        return {**state, "title_scores": scores}

    # 构建图
    graph = StateGraph(AgentState)
    graph.add_node("research", research_node)
    graph.add_node("generate_titles", generate_titles_node)
    graph.add_node("score_titles", score_titles_node)
    graph.set_entry_point("research")
    graph.add_edge("research", "generate_titles")
    graph.add_edge("generate_titles", "score_titles")
    graph.add_edge("score_titles", END)

    app = graph.compile()

    # 执行
    initial_state: AgentState = {
        "task_id": task_id,
        "topic": topic,
        "title_research": "",
        "outline_research": "",
        "content_research": "",
        "titles": [],
        "title_scores": [],
        "selected_title": "",
        "need_image": False,
        "image_source": "",
        "outline": "",
        "outline_confirmed": False,
        "content": "",
        "review_result": {},
        "review_count": 0,
        "review_feedback": "",
        "research_suggestions": "",
        "formatted_content": "",
        "progress": "",
        "error": None,
    }

    result = app.invoke(initial_state)
    return result["titles"]


# ============================================================
# 阶段2：大纲调研 + 生成大纲
# ============================================================

def run_generate_outline(
    db: Session,
    task_id: int,
    selected_title: str,
    need_image: bool = False,
    article_style: Optional[str] = None,
    article_style_custom: Optional[str] = None,
    extra_requirements: Optional[str] = None,
) -> str:
    """
    阶段2：保存配置 → 大纲调研 → 生成大纲
    配图方式（搜索/AI生成）在大纲确认页配置，不参与大纲生成
    """
    # 保存标题和配图配置 + 文章风格 + 对大纲的额外要求
    TaskService.select_title_and_config(
        db, task_id, selected_title, need_image,
        article_style, article_style_custom, extra_requirements
    )
    TaskService.update_status(db, task_id, TaskStatus.RESEARCHING_OUTLINE)

    task = TaskService.get_task(db, task_id)
    topic = task.topic if task else ""

    def research_node(state: AgentState) -> AgentState:
        TaskService.update_progress(db, task_id, "正在分析同类文章大纲结构...")
        research = researcher.research_for_outline(
            topic, selected_title,
            article_style=article_style or "",
            article_style_custom=article_style_custom or "",
        )
        TaskService.save_outline_research(db, task_id, research)
        return {**state, "outline_research": research}

    def generate_outline_node(state: AgentState) -> AgentState:
        TaskService.update_status(db, task_id, TaskStatus.GENERATING_OUTLINE)
        TaskService.update_progress(db, task_id, "正在生成大纲...")
        outline = outliner.generate_outline(
            selected_title,
            state["outline_research"],
            need_image,
            article_style=article_style or "",
            article_style_custom=article_style_custom or "",
            extra_requirements=extra_requirements,
        )
        TaskService.save_outline(db, task_id, outline)
        return {**state, "outline": outline}

    graph = StateGraph(AgentState)
    graph.add_node("research", research_node)
    graph.add_node("generate_outline", generate_outline_node)
    graph.set_entry_point("research")
    graph.add_edge("research", "generate_outline")
    graph.add_edge("generate_outline", END)

    app = graph.compile()

    initial_state: AgentState = {
        "task_id": task_id,
        "topic": topic,
        "title_research": "",
        "outline_research": "",
        "content_research": "",
        "titles": [],
        "title_scores": [],
        "selected_title": selected_title,
        "need_image": need_image,
        "image_source": "",
        "outline": "",
        "outline_confirmed": False,
        "content": "",
        "review_result": {},
        "review_count": 0,
        "review_feedback": "",
        "formatted_content": "",
        "progress": "",
        "error": None,
    }

    result = app.invoke(initial_state)
    return result["outline"]


# ============================================================
# 阶段3：生成正文 → 审稿循环 → 格式化
# ============================================================

def run_generate_content(db: Session, task_id: int) -> str:
    """
    阶段3：生成正文 → 审稿循环 → 配图（如需要）→ 格式化
    多 Agent 协作：写手 → 审稿 → 写手修改 → ... → 配图设计师 → 排版师
    """
    task = TaskService.get_task(db, task_id)
    if not task:
        raise ValueError(f"任务 {task_id} 不存在")

    selected_title = task.selected_title or ""
    outline = task.outline or ""
    topic = task.topic or ""
    # 正文写作配置（来自大纲确认页）
    word_count = task.word_count
    level = task.level
    content_extra_requirements = task.content_extra_requirements
    # 文章风格（来自标题选择页）
    article_style = task.article_style or ""
    article_style_custom = task.article_style_custom or ""
    need_image = task.need_image

    # 阶段3开头：正文调研
    TaskService.update_status(db, task_id, TaskStatus.RESEARCHING_CONTENT)

    def research_content_node(state: AgentState) -> AgentState:
        """正文调研节点：联网检索最新支撑内容和可靠数据"""
        TaskService.update_progress(db, task_id, "正在分析标题和大纲...")
        TaskService.update_progress(db, task_id, "正在联网搜索相关内容...")
        research = researcher.research_for_content(topic, selected_title, outline)
        TaskService.save_content_research(db, task_id, research)
        TaskService.update_progress(db, task_id, "调研完成，准备撰写正文...")
        return {**state, "content_research": research}

    def write_node(state: AgentState) -> AgentState:
        """写手节点：生成或修改正文"""
        review_count = state["review_count"]
        if review_count == 0:
            TaskService.update_status(db, task_id, TaskStatus.GENERATING_CONTENT)
            TaskService.update_progress(db, task_id, "正在撰写正文...")
            # 首次写作：先生成写作思路（展示给用户）
            try:
                thoughts = writer.generate_thoughts(
                    selected_title,
                    outline,
                    state.get("content_research", ""),
                    word_count=word_count,
                    level=level,
                    content_extra_requirements=content_extra_requirements,
                )
                TaskService.save_writing_thoughts(db, task_id, thoughts)
            except Exception as e:
                # 思路生成失败不阻塞正文
                TaskService.save_writing_thoughts(db, task_id, f"（写作思路生成失败：{e}）")
        else:
            TaskService.update_progress(db, task_id, f"正在根据审稿意见修改（第{review_count}次修改）...")

        content = writer.generate_content(
            outline,
            selected_title,
            state["review_feedback"],
            state.get("content_research", ""),
            word_count=word_count,
            level=level,
            content_extra_requirements=content_extra_requirements,
        )
        TaskService.save_content(db, task_id, content)
        return {**state, "content": content}

    def review_node(state: AgentState) -> AgentState:
        """审稿节点：检查质量"""
        TaskService.update_status(db, task_id, TaskStatus.REVIEWING)
        TaskService.update_progress(db, task_id, "正在审阅文章...")
        review_result = reviewer.review_content(
            state["content"],
            selected_title,
            outline=state.get("outline", ""),
            content_research=state.get("content_research", ""),
            article_style=article_style,
            article_style_custom=article_style_custom,
            word_count=word_count,
        )
        TaskService.save_review_feedback(
            db, task_id,
            json.dumps(review_result, ensure_ascii=False),
            review_result["passed"],
        )

        # 构造审稿意见给写手（条理清晰的1.2.3...点）
        review_opinions = review_result.get("review_opinions", [])
        if review_opinions:
            feedback_lines = []
            for op in review_opinions:
                point = op.get("point", "")
                where = op.get("where", "")
                why = op.get("why", "")
                expected = op.get("expected", "")
                feedback_lines.append(f"{point}. 位置：{where}\n   原因：{why}\n   期望：{expected}")
            review_feedback_text = "审稿意见（请逐条修改）：\n" + "\n".join(feedback_lines)
        else:
            review_feedback_text = ""

        # 构造调研建议给重新调研节点
        research_list = review_result.get("research_list", [])
        research_suggestions_text = ""
        if review_result.get("need_re_research") and research_list:
            research_type = review_result.get("research_type", "补充调研")
            research_suggestions_text = f"需要{research_type}，调研方向：\n" + "\n".join([f"- {r}" for r in research_list])

        return {
            **state,
            "review_result": review_result,
            "review_count": state["review_count"] + 1,
            "review_feedback": review_feedback_text,
            "research_suggestions": research_suggestions_text,
        }

    def research_again_node(state: AgentState) -> AgentState:
        """重新调研节点：审稿打回后，根据审稿建议补充调研或重新调研，更新调研素材供写手重写"""
        TaskService.update_status(db, task_id, TaskStatus.RESEARCHING_CONTENT)
        research_suggestions = state.get("research_suggestions", "")
        review_result = state.get("review_result", {})

        # 判断调研模式：补充调研（追加）还是重新调研（覆盖）
        research_type = review_result.get("research_type", "")
        if research_type == "补充调研":
            research_mode = "supplement"
            TaskService.update_progress(db, task_id, "根据审稿建议补充调研（保留原有调研结果）...")
        else:
            research_mode = "redo"
            TaskService.update_progress(db, task_id, "根据审稿建议重新调研（覆盖原有调研结果）...")

        # 调用调研节点，传入模式参数
        new_research = researcher.research_for_content(
            topic, selected_title, outline,
            extra_suggestions=research_suggestions,
            research_mode=research_mode
        )

        # 补充调研模式：把新结果追加到旧结果后面，保留原有资料
        if research_mode == "supplement":
            old_research = state.get("content_research", "")
            if old_research and old_research.strip():
                combined_research = old_research + "\n\n" + "=" * 40 + "\n\n" + new_research
            else:
                combined_research = new_research
            TaskService.save_content_research(db, task_id, combined_research)
            TaskService.update_progress(db, task_id, "补充调研完成（已追加到原有结果），准备重写正文...")
            return {**state, "content_research": combined_research}
        else:
            # 重新调研模式：直接覆盖旧结果
            TaskService.save_content_research(db, task_id, new_research)
            TaskService.update_progress(db, task_id, "重新调研完成（已覆盖原有结果），准备重写正文...")
            return {**state, "content_research": new_research}

    def should_continue_after_review(state: AgentState) -> str:
        """条件边：审稿通过后，判断需要配图还是直接格式化；不通过时判断是否需要重新调研"""
        review_result = state["review_result"]
        review_count = state["review_count"]

        if review_result.get("passed", False) or review_count >= settings.max_review_rounds:
            # 审稿通过或达到上限，判断是否需要配图
            if state.get("need_image", False):
                TaskService.update_progress(db, task_id, "审稿通过，正在配图...")
                return "image"
            else:
                TaskService.update_progress(db, task_id, "审稿通过，正在格式化...")
                return "format"
        else:
            # 审稿不通过：如果有调研补充建议，先重新调研再重写；否则直接重写
            research_suggestions = state.get("research_suggestions", "")
            if research_suggestions and research_suggestions.strip():
                TaskService.update_progress(db, task_id, f"审稿未通过（{review_result.get('score', 0)}分），根据审稿建议补充调研后重写（第{review_count}次打回）...")
                return "research_again"
            else:
                TaskService.update_progress(db, task_id, f"审稿未通过，返回修改（已修改{review_count}次）...")
                return "write"

    def should_continue_after_write(state: AgentState) -> str:
        """条件边：关闭审稿时，写完正文直接判断配图还是格式化"""
        if state.get("need_image", False):
            TaskService.update_progress(db, task_id, "正文完成，正在配图...")
            return "image"
        else:
            TaskService.update_progress(db, task_id, "正文完成，正在格式化...")
            return "format"

    def image_node(state: AgentState) -> AgentState:
        """配图设计师节点：分析配图位置上下文，生成专业关键词/prompt，获取图片并插入正文"""
        TaskService.update_status(db, task_id, TaskStatus.GENERATING_IMAGES)
        TaskService.update_progress(db, task_id, "正在分析配图位置并生成图片...")

        image_source = state.get("image_source", "ai")
        content_with_images, inserted_urls = image_agent.process_images(
            state["content"], image_source, task_id=task_id
        )

        # 保存图片URL
        TaskService.save_image_urls(db, task_id, inserted_urls)

        return {**state, "content": content_with_images}

    def format_node(state: AgentState) -> AgentState:
        """排版节点：纯规则格式化 Markdown，不调用 LLM"""
        TaskService.update_status(db, task_id, TaskStatus.FORMATTING)
        TaskService.update_progress(db, task_id, "正在格式化文章...")
        formatted = format_markdown(state["content"])
        TaskService.save_formatted_content(db, task_id, formatted)
        return {**state, "formatted_content": formatted}

    # 构建图
    graph = StateGraph(AgentState)
    graph.add_node("research_content", research_content_node)
    graph.add_node("write", write_node)
    graph.add_node("image", image_node)
    graph.add_node("format", format_node)

    # 入口：正文调研 → 写正文
    graph.set_entry_point("research_content")
    graph.add_edge("research_content", "write")

    if settings.enable_review:
        # 启用审稿：write → review → 条件(research_again/write/image/format)
        graph.add_node("review", review_node)
        graph.add_node("research_again", research_again_node)
        graph.add_edge("write", "review")
        graph.add_edge("research_again", "write")  # 重新调研后重写
        graph.add_conditional_edges(
            "review",
            should_continue_after_review,
            {
                "research_again": "research_again",
                "write": "write",
                "image": "image",
                "format": "format",
            },
        )
    else:
        # 关闭审稿：write → 条件(image/format)，速度更快
        graph.add_conditional_edges(
            "write",
            should_continue_after_write,
            {
                "image": "image",
                "format": "format",
            },
        )

    graph.add_edge("image", "format")
    graph.add_edge("format", END)

    app = graph.compile()

    initial_state: AgentState = {
        "task_id": task_id,
        "topic": task.topic,
        "title_research": task.title_research or "",
        "outline_research": task.outline_research or "",
        "content_research": "",
        "titles": [],
        "title_scores": [],
        "selected_title": selected_title,
        "need_image": task.need_image or False,
        "image_source": task.image_source or "",
        "outline": outline,
        "outline_confirmed": True,
        "content": "",
        "review_result": {},
        "review_count": 0,
        "review_feedback": "",
        "research_suggestions": "",
        "formatted_content": "",
        "progress": "",
        "error": None,
    }

    result = app.invoke(initial_state)
    return result["formatted_content"] or result["content"]
