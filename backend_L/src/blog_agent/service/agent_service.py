"""Agent 编排服务：把 LangGraph 图接入 HTTP 层。

关键设计：
1. 分段执行——作者在选标题、确认大纲时决定下一阶段的输入：
   - 标题阶段：title_graph + 标题质量门（打回循环）→ 写库 title_generated
   - 大纲阶段：outline_graph + 大纲质量门（打回循环）→ 写库 outline_generated
   - 正文阶段：content_graph + 正文质量门 → 配图及排版 → 写库 completed
2. 持久化队列的 Worker 执行阶段，前端订阅任务进度。
3. 每次阶段执行使用独立 DB session 和供应商调用预算。
"""
import json
import logging
from openai import APIError, APITimeoutError, AuthenticationError, RateLimitError
from pydantic import ValidationError

from config.settings import settings
from src.blog_agent.agent.agents import image_agent
from src.blog_agent.agent.agents.formatter import format_markdown
from src.blog_agent.agent.agents.outliner_prompts import REVIEW_OUTLINE_SYSTEM
from src.blog_agent.agent.agents.prompt_utils import IMAGE_MARKER_RE
from src.blog_agent.agent.agents.reviewer_prompts import REVIEW_CONTENT_SYSTEM
from src.blog_agent.agent.agents.title_prompts import REVIEW_TITLES_SYSTEM, TitleList
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
    count_image_marks,
    make_apply_feedback_node,
    make_quality_gate_node,
)
from src.blog_agent.agent.nodes.body_length import rewrite_to_word_range
from src.blog_agent.clients.provider_budget import ProviderLimitError, provider_run
from src.blog_agent.db.models import TaskStatus
from src.blog_agent.db.session import SessionLocal
from src.blog_agent.service.task_service import TaskService

logger = logging.getLogger(__name__)

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

_STAGES = {
    "title": ("标题", TaskStatus.RESEARCHING_TITLE, TaskStatus.GENERATING_TITLES, TaskStatus.REVIEWING_TITLE),
    "outline": ("大纲", TaskStatus.RESEARCHING_OUTLINE, TaskStatus.GENERATING_OUTLINE, TaskStatus.REVIEWING_OUTLINE),
    "content": ("正文", TaskStatus.RESEARCHING_CONTENT, TaskStatus.GENERATING_CONTENT, TaskStatus.REVIEWING),
}


def _checkpoint_outputs(db, task_id: int, status: TaskStatus, progress: str, outputs: dict) -> None:
    """Commit finished node outputs and their progress together before invoking the next provider."""
    task = TaskService.get_task(db, task_id)
    if task is None:
        return
    for field in ("title_research", "outline_research", "content_research", "evidence_sources",
                  "outline", "writing_thoughts", "content"):
        if field in outputs:
            setattr(task, field, outputs[field])
    if "titles" in outputs:
        task.titles = json.dumps(outputs["titles"], ensure_ascii=False)
        task.title_scores = None  # A previous round's scores describe different candidates.
    if "title_scores" in outputs:
        task.title_scores = json.dumps(outputs["title_scores"], ensure_ascii=False)
    if "outline" in outputs:
        task.outline_confirmed = False
    if any(key in outputs for key in ("content", "titles", "outline")):
        task.review_feedback = None
    task.status = status
    task.progress = progress
    db.commit()  # Uses the worker's fenced session; the job stays running.


def _generate_and_review(db, task_id: int, stage: str, graph, gate, state: dict) -> dict:
    """让子图的实际节点驱动进度；三个阶段遵守同一个修改上限。"""
    label, researching, generating, reviewing = _STAGES[stage]
    max_revisions = state["max_review_rounds"]
    for attempt in range(max_revisions + 1):
        review_progress = f"正在审核{label}（第 {attempt + 1} 轮）" if settings.enable_review else f"正在检查{label}"
        output_steps = {
            "research_summary": (generating, f"调研已完成，正在撰写{label}"),
            "author_material": (generating, "正在按作者简报撰写正文"),
            "title_generate": (generating, "正在为候选标题评分"),
            "title_score": (reviewing, review_progress),
            "outline_generate": (reviewing, review_progress),
            "short_outline": (reviewing, review_progress),
            "content_generate": (reviewing, "正在核对正文字数"),
        }
        if attempt:
            TaskService.update_status(db, task_id, generating, f"正在按审稿意见修改{label}（第 {attempt} 次）")
        for mode, event in graph.stream(state, stream_mode=["values", "updates"]):
            if mode == "values":
                state = event
            elif "research_start" in event:
                TaskService.update_status(db, task_id, researching, f"正在为{label}检索资料")
            else:
                for node, outputs in event.items():
                    if node in output_steps:
                        status, progress = output_steps[node]
                        _checkpoint_outputs(db, task_id, status, progress, outputs)

        if stage == "content":
            _, changed = rewrite_to_word_range(state)
            if changed:
                _checkpoint_outputs(db, task_id, reviewing, review_progress, {"content": state["content"]})
            elif settings.enable_review:
                TaskService.update_status(db, task_id, reviewing, review_progress)
        state["review_result"] = gate(state)["review_result"]
        if state["review_result"]["passed"] or attempt == max_revisions:
            return state
        state.update(_APPLY_FEEDBACK(state))
    raise ValueError("最大修改次数不能小于零")


def _failure_message(error: Exception) -> str:
    # The OpenAI SDK wraps transport exceptions in APIConnectionError.
    cause = error
    while cause is not None:
        if isinstance(cause, ProviderLimitError):
            return str(cause)
        cause = cause.__cause__
    if isinstance(error, APITimeoutError):
        return "模型服务响应超时，请稍后重试。"
    if isinstance(error, RateLimitError):
        return "模型服务当前限流，请稍后重试。"
    if isinstance(error, AuthenticationError):
        return "模型服务认证失败，请联系管理员检查配置。"
    if isinstance(error, APIError):
        return "模型服务请求未完成，请稍后重试。"
    if isinstance(error, ValidationError) and error.title == "TitleList":
        return "候选标题格式无效。需要三个不同的标题，每个为 1–30 字，请重新生成。"
    return str(error)


@provider_run()
def _run_title_stage(task_id: int, topic: str):
    """调研和评审后，交给作者选择标题。"""
    db = SessionLocal()
    try:
        task = TaskService.get_task(db, task_id)
        if not task:
            return
        state = _generate_and_review(
            db, task_id, "title", _TITLE_GRAPH, _TITLE_GATE,
            {"topic": topic, "purpose": task.purpose, "level": task.level, "word_count": task.word_count,
             "article_style": task.article_style, "article_style_custom": task.article_style_custom,
             "max_review_rounds": settings.max_review_rounds},
        )
        titles = TitleList(titles=state.get("titles") or []).titles
        progress = ("标题已生成，请选择标题并配置文章风格" if state["review_result"]["passed"]
                    else "标题自动审核未通过，请检查候选标题或重新生成")
        TaskService.save_titles(db, task_id, titles, scores=state.get("title_scores"),
                                progress=progress, review=state["review_result"])
    except Exception as e:
        db.rollback()
        TaskService.mark_failed(db, task_id, _failure_message(e))
    finally:
        db.close()


@provider_run()
def _run_outline_stage(task_id: int, selected_title: str, need_image: bool,
                       article_style: str | None, article_style_custom: str | None,
                       extra_requirements: str | None):
    """使用作者确认的标题与风格，完成大纲后交给作者编辑。"""
    db = SessionLocal()
    try:
        task = TaskService.get_task(db, task_id)
        if not task:
            return
        state = {
            "task_id": task_id,
            "topic": task.topic,
            "selected_title": selected_title,
            "purpose": task.purpose,
            "level": task.level,
            "word_count": task.word_count,
            "article_style": article_style,
            "article_style_custom": article_style_custom,
            "need_image": need_image,
            "extra_requirements": extra_requirements,
            "max_review_rounds": settings.max_review_rounds,
        }
        config_fields = ("selected_title", "need_image", "article_style", "article_style_custom", "extra_requirements")
        if any(getattr(task, field) != state[field] for field in config_fields):
            TaskService.select_title_and_config(
                db, task_id, selected_title, need_image, article_style, article_style_custom, extra_requirements
            )
        state = _generate_and_review(db, task_id, "outline", _OUTLINE_GRAPH, _OUTLINE_GATE, state)
        if not (state.get("outline") or "").strip():
            raise ValueError("未生成大纲，请重试。")
        progress = ("大纲已生成，请确认或修改" if state["review_result"]["passed"]
                    else "大纲自动审核未通过，请检查并修改大纲或重新生成")
        TaskService.save_outline(db, task_id, state["outline"], progress=progress, review=state["review_result"])
    except Exception as e:
        db.rollback()
        TaskService.mark_failed(db, task_id, _failure_message(e))
    finally:
        db.close()


@provider_run()
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
        state = {
            "task_id": task_id,
            "topic": task.topic,
            "selected_title": task.selected_title,
            "purpose": task.purpose,
            "article_style": task.article_style,
            "article_style_custom": task.article_style_custom,
            "need_image": task.need_image,
            "image_source": task.image_source,
            "word_count": task.word_count,
            "level": task.level,
            "extra_requirements": task.extra_requirements,
            "content_extra_requirements": task.content_extra_requirements,
            "outline": task.outline,
            "max_review_rounds": settings.max_review_rounds,
        }
        state = _generate_and_review(db, task_id, "content", _CONTENT_GRAPH, _CONTENT_GATE, state)
        TaskService.save_reviewed_draft(db, task_id, state)
        if not state["review_result"]["passed"]:
            opinions = state["review_result"].get("review_opinions") or []
            detail = "；".join(o.get("why", "") for o in opinions if o.get("why"))
            TaskService.mark_failed(db, task_id, "正文自动审核未通过。" + (detail or "请重新生成正文。"))
            return

        # ========== 阶段9：配图 + 排版（正文生成后） ==========
        task = TaskService.get_task(db, task_id)
        content = task.content or ""
        completion = "全部完成"
        if task.need_image:
            requested_images = count_image_marks(content)
            TaskService.update_status(db, task_id, TaskStatus.GENERATING_IMAGES, "正在为文章配图")
            try:
                content, image_urls = image_agent.process_images(content, task.image_source or "api", task_id)
            except Exception as error:
                logger.warning("任务 %d 的配图失败，继续交付正文：%s", task_id, type(error).__name__)
                content, image_urls = IMAGE_MARKER_RE.sub("", content), []
            TaskService.save_image_urls(db, task_id, image_urls)
            if not requested_images:
                completion = "文章已完成；确认的大纲未指定配图位置，本次未添加图片"
            elif len(image_urls) < requested_images:
                completion = f"文章已完成，成功配图 {len(image_urls)}/{requested_images} 张"
        TaskService.update_status(db, task_id, TaskStatus.FORMATTING, "正在格式化文章")
        formatted = format_markdown(content)
        TaskService.save_formatted_content(db, task_id, formatted, progress=completion)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        TaskService.mark_failed(db, task_id, _failure_message(e))
    finally:
        db.close()
