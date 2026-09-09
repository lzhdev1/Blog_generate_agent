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
    FormatterAgent,
    ImageAgent,
)
from src.blog_agent.service.task_service import TaskService
from src.blog_agent.db.models import TaskStatus
from config.settings import settings

# 初始化各个 Agent
researcher = ResearcherAgent()
title_agent = TitleAgent()
outliner = OutlinerAgent()
writer = WriterAgent()
reviewer = ReviewerAgent()
formatter = FormatterAgent()
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
        TaskService.update_progress(db, task_id, "研究员正在分析同类文章标题...")
        research = researcher.research_for_titles(topic)
        TaskService.save_title_research(db, task_id, research)
        return {**state, "title_research": research}

    def generate_titles_node(state: AgentState) -> AgentState:
        TaskService.update_progress(db, task_id, "标题策划正在生成标题...")
        titles = title_agent.generate_titles(topic, state["title_research"])
        TaskService.save_titles(db, task_id, titles)
        return {**state, "titles": titles}

    # 构建图
    graph = StateGraph(AgentState)
    graph.add_node("research", research_node)
    graph.add_node("generate_titles", generate_titles_node)
    graph.set_entry_point("research")
    graph.add_edge("research", "generate_titles")
    graph.add_edge("generate_titles", END)

    app = graph.compile()

    # 执行
    initial_state: AgentState = {
        "task_id": task_id,
        "topic": topic,
        "title_research": "",
        "outline_research": "",
        "titles": [],
        "selected_title": "",
        "need_image": False,
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
    return result["titles"]


# ============================================================
# 阶段2：大纲调研 + 生成大纲
# ============================================================

def run_generate_outline(
    db: Session,
    task_id: int,
    selected_title: str,
    need_image: bool = False,
    image_source: Optional[str] = None,
) -> str:
    """
    阶段2：保存配置 → 大纲调研 → 生成大纲
    """
    # 保存标题和配图配置
    TaskService.select_title_and_config(db, task_id, selected_title, need_image, image_source)
    TaskService.update_status(db, task_id, TaskStatus.RESEARCHING_OUTLINE)

    task = TaskService.get_task(db, task_id)
    topic = task.topic if task else ""

    def research_node(state: AgentState) -> AgentState:
        TaskService.update_progress(db, task_id, "研究员正在分析同类文章大纲结构...")
        research = researcher.research_for_outline(topic, selected_title)
        TaskService.save_outline_research(db, task_id, research)
        return {**state, "outline_research": research}

    def generate_outline_node(state: AgentState) -> AgentState:
        TaskService.update_progress(db, task_id, "大纲师正在生成大纲...")
        outline = outliner.generate_outline(
            selected_title,
            state["outline_research"],
            need_image,
            image_source or "",
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
        "titles": [],
        "selected_title": selected_title,
        "need_image": need_image,
        "image_source": image_source or "",
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

    TaskService.update_status(db, task_id, TaskStatus.GENERATING_CONTENT)

    def write_node(state: AgentState) -> AgentState:
        """写手节点：生成或修改正文"""
        review_count = state["review_count"]
        if review_count == 0:
            TaskService.update_progress(db, task_id, "写手正在撰写正文...")
        else:
            TaskService.update_progress(db, task_id, f"写手正在根据审稿意见修改（第{review_count}次修改）...")

        content = writer.generate_content(
            outline,
            selected_title,
            state["review_feedback"],
        )
        TaskService.save_content(db, task_id, content)
        return {**state, "content": content}

    def review_node(state: AgentState) -> AgentState:
        """审稿节点：检查质量"""
        TaskService.update_progress(db, task_id, "审稿编辑正在审阅文章...")
        review_result = reviewer.review_content(state["content"], selected_title)
        TaskService.save_review_feedback(
            db, task_id,
            json.dumps(review_result, ensure_ascii=False),
            review_result["passed"],
        )
        return {
            **state,
            "review_result": review_result,
            "review_count": state["review_count"] + 1,
            "review_feedback": review_result["feedback"] + "\n问题：" + "；".join(review_result["issues"]) + "\n建议：" + "；".join(review_result["suggestions"]),
        }

    def should_continue_after_review(state: AgentState) -> str:
        """条件边：审稿通过后，判断需要配图还是直接格式化"""
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
            TaskService.update_progress(db, task_id, f"审稿未通过，返回修改（已修改{review_count}次）...")
            return "write"

    def image_node(state: AgentState) -> AgentState:
        """配图设计师节点：根据大纲标注的位置配图，插入正文"""
        TaskService.update_status(db, task_id, TaskStatus.GENERATING_IMAGES)
        TaskService.update_progress(db, task_id, "配图设计师正在提取配图位置...")

        # 1. 从大纲中提取配图位置
        image_positions = image_agent.extract_image_positions(outline)
        if not image_positions:
            TaskService.update_progress(db, task_id, "未找到配图位置，跳过配图...")
            return state

        # 2. 逐个获取图片
        image_urls = []
        for i, pos in enumerate(image_positions):
            TaskService.update_progress(db, task_id, f"正在获取第{i+1}/{len(image_positions)}张配图...")
            image_url = image_agent.get_image(pos["description"], state.get("image_source", "ai"))
            image_urls.append(image_url)

        # 3. 把图片插入正文
        TaskService.update_progress(db, task_id, "正在将图片插入正文...")
        content_with_images, inserted_urls = image_agent.insert_images_to_content(
            state["content"], image_positions, image_urls
        )

        # 4. 保存图片URL
        TaskService.save_image_urls(db, task_id, [u for u in inserted_urls if u])

        return {**state, "content": content_with_images}

    def format_node(state: AgentState) -> AgentState:
        """排版师节点：格式化"""
        TaskService.update_status(db, task_id, TaskStatus.FORMATTING)
        TaskService.update_progress(db, task_id, "排版师正在格式化文章...")
        formatted = formatter.format_content(state["content"])
        TaskService.save_formatted_content(db, task_id, formatted)
        return {**state, "formatted_content": formatted}

    # 构建图：write → review → (条件) write/image/format → END
    graph = StateGraph(AgentState)
    graph.add_node("write", write_node)
    graph.add_node("review", review_node)
    graph.add_node("image", image_node)
    graph.add_node("format", format_node)

    graph.set_entry_point("write")
    graph.add_edge("write", "review")
    graph.add_conditional_edges(
        "review",
        should_continue_after_review,
        {
            "write": "write",
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
        "titles": [],
        "selected_title": selected_title,
        "need_image": task.need_image or False,
        "image_source": task.image_source or "",
        "outline": outline,
        "outline_confirmed": True,
        "content": "",
        "review_result": {},
        "review_count": 0,
        "review_feedback": "",
        "formatted_content": "",
        "progress": "",
        "error": None,
    }

    result = app.invoke(initial_state)
    return result["formatted_content"] or result["content"]
