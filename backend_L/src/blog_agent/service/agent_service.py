"""Agent 编排服务：把 LangGraph 图接入 HTTP 层。

关键设计：
1. 分段执行——主流程有两个人肉介入点（选标题、确认大纲），不能一次性跑完整主图：
   - 标题阶段：title_graph + 标题质量门（打回循环）→ 写库 title_generated
   - 大纲阶段：outline_graph + 大纲质量门（打回循环）→ 写库 outline_generated
   - 正文阶段：content_graph + 正文质量门（打回循环，含补充/重新调研）→ 写库 content_generated
2. 后台线程执行——LLM 全链路耗时数分钟，接口立即返回，前端轮询 GET /task/{id}
3. 每个后台任务使用独立 DB session（线程安全）
"""
from concurrent.futures import ThreadPoolExecutor

from config.settings import settings
from src.blog_agent.agent.agents import image_agent
from src.blog_agent.agent.agents.formatter import format_markdown
from src.blog_agent.agent.agents.outliner_prompts import REVIEW_OUTLINE_SYSTEM
from src.blog_agent.agent.agents.reviewer_prompts import REVIEW_CONTENT_SYSTEM
from src.blog_agent.agent.agents.title_prompts import REVIEW_TITLES_SYSTEM
from src.blog_agent.agent.graphs.content_graph import build_content_graph
from src.blog_agent.agent.graphs.outline_graph import build_outline_graph
from src.blog_agent.agent.graphs.supervisor_graph import (
    _build_content_review_task,
    _build_outline_review_task,
    _build_title_review_task,
)
from src.blog_agent.agent.graphs.title_graph import build_title_graph
from src.blog_agent.agent.nodes.quality_gate import (
    OutlineReviewResult,
    ReviewResult,
    TitleReviewResult,
    make_apply_feedback_node,
    make_quality_gate_node,
)
from src.blog_agent.db.models import TaskStatus
from src.blog_agent.db.session import SessionLocal
from src.blog_agent.service.task_service import TaskService

# 线程池：并发执行后台生成任务（并发数由 settings.agent_max_workers 配置）
_executor = ThreadPoolExecutor(max_workers=settings.agent_max_workers)

# 图与质量门实例缓存（LangGraph compiled graph 可并发 invoke，实例线程安全）
_TITLE_GRAPH = build_title_graph()
_OUTLINE_GRAPH = build_outline_graph()
_CONTENT_GRAPH = build_content_graph()

_TITLE_GATE = make_quality_gate_node(
    REVIEW_TITLES_SYSTEM, _build_title_review_task, TitleReviewResult, "reviewer"
)
_OUTLINE_GATE = make_quality_gate_node(
    REVIEW_OUTLINE_SYSTEM, _build_outline_review_task, OutlineReviewResult, "reviewer"
)
_CONTENT_GATE = make_quality_gate_node(
    REVIEW_CONTENT_SYSTEM, _build_content_review_task, ReviewResult, "reviewer"
)
_APPLY_FEEDBACK = make_apply_feedback_node()


# ========== 各阶段执行（后台线程内运行） ==========

def _run_title_stage(task_id: int, topic: str):
    """调研标题 → 生成标题 → 质量门打回循环 → 写库（status=title_generated）"""
    import time
    db = SessionLocal()
    try:
        TaskService.update_status(db, task_id, TaskStatus.RESEARCHING_TITLE)
        TaskService.update_progress(db, task_id, "正在调研同类文章标题...")
        state = {"topic": topic, "max_review_rounds": settings.max_review_rounds}
        max_rounds = settings.max_review_rounds
        for r in range(max_rounds + 1):
            # 阶段1：调研 + 生成（打回时跳过调研，直接用已有 title_research）
            if r == 0:
                TaskService.update_status(db, task_id, TaskStatus.RESEARCHING_TITLE)
                TaskService.update_progress(db, task_id, "正在调研并生成标题...")
            else:
                TaskService.update_progress(db, task_id, f"第 {r} 次打回，正在根据审稿意见重新生成标题...")
            t_gen = time.time()
            state = _TITLE_GRAPH.invoke(state)
            gen_cost = time.time() - t_gen

            # 阶段2：主编审核（独立状态，独立进度）
            TaskService.update_status(db, task_id, TaskStatus.REVIEWING_TITLE)
            TaskService.update_progress(db, task_id, f"正在审核标题质量（生成耗时 {gen_cost:.1f}s）...")
            t_gate = time.time()
            state["review_result"] = _TITLE_GATE(state)["review_result"]
            gate_cost = time.time() - t_gate

            if state["review_result"].get("passed") or r >= max_rounds:
                TaskService.update_progress(
                    db, task_id,
                    f"标题审核通过（生成 {gen_cost:.1f}s + 审核 {gate_cost:.1f}s）"
                )
                break
            TaskService.update_progress(
                db, task_id,
                f"标题质量不达标（生成 {gen_cost:.1f}s + 审核 {gate_cost:.1f}s），正在重新生成..."
            )
            state.update(_APPLY_FEEDBACK(state))
        TaskService.save_title_research(db, task_id, state.get("title_research") or "")
        TaskService.save_titles(
            db, task_id, state.get("titles") or [],
            scores=state.get("title_scores") or None,
        )
    except Exception as e:  # noqa: BLE001  后台任务必须吞掉异常并落库
        TaskService.mark_failed(db, task_id, str(e))
    finally:
        db.close()


def _run_outline_stage(task_id: int, selected_title: str, need_image: bool,
                       article_style: str | None, article_style_custom: str | None,
                       extra_requirements: str | None):
    """保存标题配置 → 调研大纲结构 → 生成大纲 → 质量门打回循环 → 写库（status=outline_generated）"""
    db = SessionLocal()
    try:
        task = TaskService.get_task(db, task_id)
        if not task:
            return
        TaskService.select_title_and_config(
            db, task_id, selected_title, need_image,
            article_style=article_style, article_style_custom=article_style_custom,
            extra_requirements=extra_requirements,
        )
        TaskService.update_status(db, task_id, TaskStatus.RESEARCHING_OUTLINE)
        TaskService.update_progress(db, task_id, "正在调研同类文章大纲结构...")
        state = {
            "task_id": task_id,
            "topic": task.topic,
            "selected_title": selected_title,
            "article_style": article_style,
            "article_style_custom": article_style_custom,
            "need_image": need_image,
            "extra_requirements": extra_requirements,
            "max_review_rounds": settings.max_review_rounds,
        }
        max_rounds = settings.max_review_rounds
        import time
        for r in range(max_rounds + 1):
            if r == 0:
                TaskService.update_status(db, task_id, TaskStatus.RESEARCHING_OUTLINE)
                TaskService.update_progress(db, task_id, "正在调研并生成大纲...")
            else:
                TaskService.update_progress(db, task_id, f"第 {r} 次打回，正在根据审稿意见重新生成大纲...")
            t_gen = time.time()
            state = _OUTLINE_GRAPH.invoke(state)
            gen_cost = time.time() - t_gen

            TaskService.update_status(db, task_id, TaskStatus.REVIEWING_OUTLINE)
            TaskService.update_progress(db, task_id, f"正在审核大纲质量（生成耗时 {gen_cost:.1f}s）...")
            t_gate = time.time()
            state["review_result"] = _OUTLINE_GATE(state)["review_result"]
            gate_cost = time.time() - t_gate

            if state["review_result"].get("passed") or r >= max_rounds:
                TaskService.update_progress(
                    db, task_id,
                    f"大纲审核通过（生成 {gen_cost:.1f}s + 审核 {gate_cost:.1f}s）"
                )
                break
            TaskService.update_progress(
                db, task_id,
                f"大纲质量不达标（生成 {gen_cost:.1f}s + 审核 {gate_cost:.1f}s），正在重新生成..."
            )
            state.update(_APPLY_FEEDBACK(state))
        TaskService.save_outline_research(db, task_id, state.get("outline_research") or "")
        TaskService.save_outline(db, task_id, state.get("outline") or "")
    except Exception as e:  # noqa: BLE001
        TaskService.mark_failed(db, task_id, str(e))
    finally:
        db.close()


def _run_content_stage(task_id: int):
    """调研正文素材 → 撰写正文 → 审稿 → 打回循环（含补充/重新调研）→ 配图 → 排版 → 写库（status=completed）"""
    db = SessionLocal()
    try:
        task = TaskService.get_task(db, task_id)
        if not task:
            return
        if not task.outline_confirmed:
            TaskService.mark_failed(db, task_id, "大纲尚未确认，不能生成正文")
            return
        TaskService.update_status(db, task_id, TaskStatus.RESEARCHING_CONTENT)
        TaskService.update_progress(db, task_id, "正在按大纲调研正文素材...")
        state = {
            "task_id": task_id,
            "topic": task.topic,
            "selected_title": task.selected_title,
            "article_style": task.article_style,
            "article_style_custom": task.article_style_custom,
            "need_image": task.need_image,
            "image_source": task.image_source,
            "word_count": task.word_count,
            "level": task.level,
            "content_extra_requirements": task.content_extra_requirements,
            "outline": task.outline,
            "max_review_rounds": settings.max_review_rounds,
        }
        max_rounds = settings.max_review_rounds
        for r in range(max_rounds + 1):
            TaskService.update_status(db, task_id, TaskStatus.GENERATING_CONTENT)
            TaskService.update_progress(db, task_id, "正在调研并撰写正文...")
            state = _CONTENT_GRAPH.invoke(state)
            TaskService.update_status(db, task_id, TaskStatus.REVIEWING)
            TaskService.update_progress(db, task_id, "正在审稿...")
            state["review_result"] = _CONTENT_GATE(state)["review_result"]
            if state["review_result"].get("passed") or r >= max_rounds:
                break
            TaskService.update_progress(db, task_id, "审稿未通过，正在按审稿意见补充调研并重写...")
            state.update(_APPLY_FEEDBACK(state))
            TaskService.update_status(db, task_id, TaskStatus.RESEARCHING_CONTENT)

        TaskService.save_content_research(db, task_id, state.get("content_research") or "")
        TaskService.save_writing_thoughts(db, task_id, state.get("writing_thoughts") or "")
        TaskService.save_content(db, task_id, state.get("content") or "")
        # 结构化审稿结果落库（review_feedback 字段存 JSON）
        TaskService.save_review_result(db, task_id, state.get("review_result"))

        # ========== 阶段9：配图 + 排版（正文生成后） ==========
        task = TaskService.get_task(db, task_id)
        content = task.content or ""
        if task.need_image:
            TaskService.update_status(db, task_id, TaskStatus.GENERATING_IMAGES)
            TaskService.update_progress(db, task_id, "正在为文章配图...")
            content, image_urls = image_agent.process_images(
                content, task.image_source or "api", task_id
            )
            TaskService.save_content_with_images(db, task_id, content)
            TaskService.save_image_urls(db, task_id, image_urls)
            TaskService.update_progress(db, task_id, f"配图完成（{len(image_urls)}张），正在排版...")
        TaskService.update_status(db, task_id, TaskStatus.FORMATTING)
        TaskService.update_progress(db, task_id, "正在格式化文章...")
        formatted = format_markdown(content)
        TaskService.save_formatted_content(db, task_id, formatted)  # status → completed
    except Exception as e:  # noqa: BLE001
        TaskService.mark_failed(db, task_id, str(e))
    finally:
        db.close()


# ========== 对外入口：异步提交后台任务 ==========

def start_title_stage(task_id: int, topic: str):
    """异步启动标题阶段（pending → title_generated）"""
    _executor.submit(_run_title_stage, task_id, topic)


def start_outline_stage(task_id: int, selected_title: str, need_image: bool,
                        article_style: str | None, article_style_custom: str | None,
                        extra_requirements: str | None):
    """异步启动大纲阶段（title_generated → outline_generated）"""
    _executor.submit(
        _run_outline_stage, task_id, selected_title, need_image,
        article_style, article_style_custom, extra_requirements,
    )


def start_content_stage(task_id: int):
    """异步启动正文阶段（大纲已确认 → content_generated）"""
    _executor.submit(_run_content_stage, task_id)
