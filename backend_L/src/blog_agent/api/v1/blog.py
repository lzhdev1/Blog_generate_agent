"""任务/博客 API（鉴权版：登录才能发起生成任务，作者本人管理自己的任务）

流程与旧版对齐：
create（需登录）→ generate-titles（后台跑标题阶段）→ 轮询/SSE 到 title_generated
→ submit-title-config（后台跑大纲阶段）→ 轮询/SSE 到 outline_generated
→ confirm-outline（保存正文配置）→ generate-content（后台跑正文阶段）→ 轮询/SSE 到 content_generated
→ GET /blog/{id} 查看完整产物（仅作者本人）
→ PUT /task/{id}/visibility 配置公开/下载/价格
"""
import asyncio
import hashlib
import json
from collections import Counter
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from src.blog_agent.agent.nodes.quality_gate import EDITORIAL_POLICY_VERSION, count_chars
from src.blog_agent.api.deps import get_current_user, get_db
from src.blog_agent.db.job_models import GenerationJob, GenerationRequest
from src.blog_agent.db.models import BlogTask, EditorialDraft, ManuscriptBackup, TaskStatus, User
from src.blog_agent.schemas.task_schema import (
    ConfirmOutlineReq,
    TaskCreateReq,
    TaskListResp,
    TaskResp,
    TitleAndConfigReq,
    VisibilityReq,
)
from src.blog_agent.service import job_queue, manuscript_recovery
from src.blog_agent.service.quota_service import reserve_draft
from src.blog_agent.service.task_service import TaskService

router = APIRouter(prefix="/api/v1", tags=["博客任务"])
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
_open_streams = Counter()
_stream_lock = Lock()


def _stream_slot(current_user: User = Depends(get_current_user)):
    uid = current_user.id
    with _stream_lock:
        if _open_streams[uid] >= 3:
            raise HTTPException(429, "打开的进度连接过多，请稍后重试", headers={"Retry-After": "5"})
        _open_streams[uid] += 1
    try:
        yield
    finally:
        with _stream_lock:
            _open_streams[uid] -= 1
            if not _open_streams[uid]:
                del _open_streams[uid]

# 可以等待人工操作或查看结果的状态；content_generated 兼容旧任务。
_RESTING_STATUSES = {
    TaskStatus.PENDING, TaskStatus.TITLE_GENERATED, TaskStatus.OUTLINE_GENERATED,
    TaskStatus.CONTENT_GENERATED, TaskStatus.COMPLETED, TaskStatus.FAILED,
}


def _get_owned_task(db: Session, task_id: int, user: User, *, lock: bool = False):
    """修改操作锁住任务行，使状态检查与状态迁移在同一事务中完成。"""
    query = db.query(BlogTask).filter(BlogTask.id == task_id)
    if lock:
        query = query.with_for_update().populate_existing()
    return _check_owner(query.first(), user)


def _check_owner(task, user):
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.is_demo or task.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该任务")
    return task


def _task_with_latest_job(db, *columns):
    # One SQL snapshot for both sides of a stage transition. PostgreSQL READ
    # COMMITTED can see different commits in two successive SELECTs.
    latest_id = (select(GenerationJob.id)
                 .where(GenerationJob.task_id == BlogTask.id, GenerationJob.review_only.is_(False))
                 .order_by(GenerationJob.id.desc()).limit(1)
                 .correlate(BlogTask).scalar_subquery())
    return (db.query(*columns, GenerationJob).select_from(BlogTask)
            .outerjoin(GenerationJob, GenerationJob.id == latest_id))


def _get_owned_snapshot(db, task_id, user, request_key=None):
    has_backup = select(ManuscriptBackup.task_id).where(ManuscriptBackup.task_id == BlogTask.id).exists()
    columns = [BlogTask, has_backup]
    if request_key is not None:
        key_hash = hashlib.sha256(request_key.encode()).hexdigest()
        columns.append(select(GenerationRequest.task_id).where(
            GenerationRequest.task_id == BlogTask.id, GenerationRequest.key_hash == key_hash,
        ).exists())
    row = (_task_with_latest_job(db, *columns).filter(BlogTask.id == task_id)
           .populate_existing().first())
    task = _check_owner(row[0] if row else None, user)
    response = TaskResp.model_validate(task).model_dump()
    response["job"] = _visible_job(task.status, row[-1], task.selected_title, task.outline_confirmed)
    response["can_restore_previous"] = task.status == TaskStatus.FAILED and row[1]
    if request_key is not None and row[2]:
        response["accepted_request_key"] = request_key
    return response


def _visible_job(status, job, selected_title, outline_confirmed):
    if job and job.status == "failed":
        # Restoring a saved draft can also take the author back to a different
        # failed stage. Never route that draft using the discarded attempt.
        stage = "content" if outline_confirmed else ("outline" if selected_title else "title")
        if status != TaskStatus.FAILED or stage != job.stage:
            return None
    return job_queue.job_info(job)


def _check_not_running(task: BlogTask) -> None:
    if task.status not in _RESTING_STATUSES:
        raise HTTPException(status_code=409, detail="该任务正在执行，请查看最新进度")


def _submission(db, task_id, user, key, action, payload=None, *, legacy_payload=None):
    if not key:
        return _get_owned_task(db, task_id, user, lock=True), None
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    def digest(data):
        command = json.dumps([action, data], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(command.encode()).hexdigest()

    command_hash = digest(payload)
    receipt = db.get(GenerationRequest, (task_id, key_hash))
    if receipt is None:
        task = _get_owned_task(db, task_id, user, lock=True)
        # A concurrent first delivery may have committed while we waited.
        receipt = db.get(GenerationRequest, (task_id, key_hash))
        if receipt is None:
            db.add(GenerationRequest(task_id=task_id, key_hash=key_hash, command_hash=command_hash))
            return task, None
    # Accepted receipts are immutable. Authorize the snapshot before disclosing
    # even a payload conflict, and let a replay read alongside an active editor.
    snapshot = _get_owned_snapshot(db, task_id, user)
    if receipt.command_hash != command_hash and (legacy_payload is None or receipt.command_hash != digest(legacy_payload)):
        raise HTTPException(409, {"code": "idempotency_conflict", "message": "请求标识已用于不同操作，请重新提交"})
    return None, snapshot


def _reset_content(task: BlogTask) -> None:
    task.content_research = task.writing_thoughts = task.content = None
    task.evidence_sources = None
    task.review_feedback = task.formatted_content = None
    task.image_prompts = task.image_urls = None
    # 新稿完成后由作者重新决定可见性与下载价格。
    task.is_public = task.allow_download = False
    task.download_price = 0


def _reset_outline(task: BlogTask) -> None:
    task.outline = task.outline_research = None
    task.outline_confirmed = False
    task.image_source = task.content_extra_requirements = None
    _reset_content(task)


def _start_stage(db: Session, task: BlogTask, stage: str, status: TaskStatus, progress: str):
    job = job_queue.enqueue(db, task, stage)
    task.status, task.progress, task.error = status, progress, None
    db.flush()
    response = TaskResp.model_validate(task).model_dump()
    response["job"] = job_queue.job_info(job)
    db.commit()
    return response


def _start_outline(db: Session, task: BlogTask):
    if task.outline or task.outline_research:
        manuscript_recovery.preserve(db, task)
    _reset_outline(task)
    return _start_stage(db, task, "outline", TaskStatus.RESEARCHING_OUTLINE, "大纲生成任务已排队")


# ========== 基础接口 ==========

@router.post("/task", response_model=TaskResp, summary="创建博客生成任务（需登录）")
def create_task(req: TaskCreateReq, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    """创建一个博客生成任务，状态为 pending，归属当前用户"""
    reserve_draft(db, current_user.id)
    task = TaskService.create_task(db, user_id=current_user.id, **req.model_dump())
    return task


@router.get("/task/{task_id}", response_model=TaskResp, summary="查询任务状态")
def get_task(task_id: int, db: Session = Depends(get_db),
             current_user: User = Depends(get_current_user), key: IdempotencyKey = None):
    """根据 task_id 查询任务状态（前端轮询兜底用，包含实时进度）"""
    return _get_owned_snapshot(db, task_id, current_user, key)


@router.get("/task/{task_id}/stream", summary="任务状态 SSE 推送（替代高频轮询）")
async def stream_task_status(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    slot: None = Depends(_stream_slot, scope="request"),
):
    """服务端推送任务状态变化，替代前端 2s 轮询。

    设计要点：
    1. 前置归属校验（与 GET /task/{id} 同规则，非法访问直接 401/403/404）
    2. 状态或进度文本变化才推送（同值不推，省带宽）
    3. DB 查询放线程池（run_in_threadpool），不阻塞事件循环
    4. 人工确认点、成品与失败状态送达后自动断开；关页面即停止
    5. X-Accel-Buffering: no 防止 Nginx 缓冲 SSE（生产部署关键）
    """
    # 归属校验：非法访问在这里直接返回错误响应（不进 generator）
    await run_in_threadpool(_get_owned_task, db, task_id, current_user)
    owner_id = current_user.id
    await run_in_threadpool(db.close)

    async def event_generator():
        from src.blog_agent.db.session import SessionLocal

        def _fetch():
            """线程池内执行：独立 session 查询任务状态（线程安全）"""
            with SessionLocal() as s:
                row = (_task_with_latest_job(s, BlogTask.status, BlogTask.progress, BlogTask.error,
                                             BlogTask.selected_title, BlogTask.outline_confirmed)
                       .join(User, User.id == BlogTask.user_id)
                       .filter(BlogTask.id == task_id, BlogTask.user_id == owner_id,
                               BlogTask.is_demo.is_not(True), User.is_active.is_(True)).first())
                if row is None:
                    return None
                status, progress, error, title, confirmed, job = row
                return {"status": status, "progress": progress, "error": error,
                        "job": _visible_job(status, job, title, confirmed)}

        last_sig: tuple | None = None
        deadline = asyncio.get_running_loop().time() + 600
        while asyncio.get_running_loop().time() < deadline:
            # 客户端已断开（关页面/组件卸载/跳转）→ 停止推送
            if await request.is_disconnected():
                break
            payload = await run_in_threadpool(_fetch)
            if payload is None:
                yield "event: error\ndata: {\"detail\":\"任务不存在\"}\n\n"
                break
            sig = (payload["status"], payload["progress"], payload["error"], payload["job"])
            if sig != last_sig:
                last_sig = sig
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if payload["status"] in _RESTING_STATUSES:
                    yield "event: done\ndata: {}\n\n"
                    break
            await asyncio.sleep(2)  # 服务端集中轮询 DB，客户端零请求

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭 Nginx 缓冲，保证实时推送
        },
    )


@router.delete("/task/{task_id}", summary="删除任务")
def delete_task(task_id: int, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    """根据 task_id 删除任务及其所有数据"""
    task = _get_owned_task(db, task_id, current_user, lock=True)
    _check_not_running(task)
    draft = db.get(EditorialDraft, task_id)
    if draft and draft.status in {"queued", "reviewing"}:
        raise HTTPException(409, "修订稿正在审核，待结果返回后可删除")
    TaskService.delete_task(db, task_id=task_id)
    return {"message": "删除成功", "task_id": task_id}


@router.get("/task", response_model=TaskListResp, summary="我的任务列表")
def list_tasks(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分页查询当前用户的任务列表（数据隔离，不含他人及演示数据）"""
    total, items = TaskService.list_tasks(db, limit=limit, offset=offset, user_id=current_user.id)
    return {"total": total, "items": items}


@router.put("/task/{task_id}/visibility", response_model=TaskResp, summary="配置文章可见性（公开/下载/价格）")
def update_visibility(task_id: int, req: VisibilityReq, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    """作者配置文章：是否公开、是否允许下载、下载价格"""
    task = _get_owned_task(db, task_id, current_user, lock=True)
    if task.revision != req.expected_revision:
        raise HTTPException(409, "稿件已更新，请查看当前正文后再确认发布设置")
    if task.status not in (TaskStatus.CONTENT_GENERATED, TaskStatus.COMPLETED):
        raise HTTPException(status_code=400, detail="任务未完成，暂不能配置公开/下载")
    if req.is_public and not task.is_public:
        report = TaskService.parse_review_result(task.review_feedback) or {}
        if report.get("passed") is not True or report.get("skipped") or report.get("policy_version") != EDITORIAL_POLICY_VERSION:
            raise HTTPException(409, detail={"code": "review_required", "message": "这版正文需要复审。请在修订页保存并提交审核，通过后再公开。"})
    task.is_public = req.is_public
    task.allow_download = req.allow_download
    task.download_price = req.download_price
    db.commit()
    db.refresh(task)
    return task


# ========== 节点1：调研 + 生成标题 ==========

@router.post("/task/{task_id}/generate-titles", response_model=TaskResp, summary="节点1：调研并生成标题（支持重新生成）")
def generate_titles(task_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user), key: IdempotencyKey = None):
    """先调研同类文章标题，再生成3个标题（异步执行，轮询 GET /task/{id} 看进度）"""
    task, replay = _submission(db, task_id, current_user, key, "generate-titles")
    if replay is not None:
        return replay
    _check_not_running(task)
    if task.titles or task.title_research or task.outline or task.content or task.formatted_content:
        manuscript_recovery.preserve(db, task)
    task.titles = task.title_scores = task.title_research = task.selected_title = None
    task.extra_requirements = None
    task.need_image = False
    _reset_outline(task)
    return _start_stage(db, task, "title", TaskStatus.RESEARCHING_TITLE, "标题调研任务已排队")


# ========== 人工介入点1：选择标题 + 配图配置，自动开始大纲调研和生成 ==========

@router.post("/task/{task_id}/submit-title-config", response_model=TaskResp, summary="人工介入点1：选择标题+是否配图+文章风格，自动生成大纲")
def submit_title_config(task_id: int, req: TitleAndConfigReq, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user), key: IdempotencyKey = None):
    """用户选择标题，配置是否配图、文章风格、对大纲的额外要求；提交后异步开始大纲阶段"""
    # A missing brief field keeps its current value, while an explicit null clears it.
    # Recognize pre-brief receipts only for requests representable by that older API.
    legacy = req.model_dump(exclude={"purpose"}) if "purpose" not in req.model_fields_set else None
    task, replay = _submission(db, task_id, current_user, key, "submit-title-config",
                               {"config": req.model_dump(exclude_unset=True)}, legacy_payload=legacy)
    if replay is not None:
        return replay
    _check_not_running(task)
    if task.status != TaskStatus.TITLE_GENERATED:
        raise HTTPException(status_code=400, detail="当前状态不允许选择标题")
    if req.article_style == "custom" and not req.article_style_custom:
        raise HTTPException(status_code=400, detail="选择自定义风格时，必须填写自定义风格内容")

    task.selected_title = req.title
    if "purpose" in req.model_fields_set:
        task.purpose = req.purpose
    task.need_image = req.need_image
    if "article_style" in req.model_fields_set:
        task.article_style = req.article_style
        task.article_style_custom = req.article_style_custom if req.article_style == "custom" else None
    task.extra_requirements = req.extra_requirements
    return _start_outline(db, task)


@router.post("/task/{task_id}/regenerate-outline", response_model=TaskResp, summary="重新生成大纲")
def regenerate_outline(task_id: int, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user), key: IdempotencyKey = None):
    """对大纲不满意时，重新生成大纲（使用已保存的标题、配图、风格配置）"""
    task, replay = _submission(db, task_id, current_user, key, "regenerate-outline")
    if replay is not None:
        return replay
    _check_not_running(task)
    retry = task.status == TaskStatus.FAILED and not task.outline_confirmed
    if task.status != TaskStatus.OUTLINE_GENERATED and not retry:
        raise HTTPException(status_code=400, detail="当前状态不允许重新生成大纲")
    if not task.selected_title:
        raise HTTPException(status_code=400, detail="未找到已选择的标题")

    return _start_outline(db, task)


# ========== 人工介入点2：确认大纲 ==========

@router.post("/task/{task_id}/reopen-outline", response_model=TaskResp, summary="正文失败后返回大纲编辑")
def reopen_outline(task_id: int, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    task = _get_owned_task(db, task_id, current_user, lock=True)
    _check_not_running(task)
    if (task.status != TaskStatus.FAILED or task.is_public or
            not task.outline_confirmed or not (task.outline or "").strip()):
        raise HTTPException(status_code=409, detail="只有正文生成失败的私有文稿可以返回大纲编辑")
    if task.content or task.formatted_content or task.content_research:
        manuscript_recovery.preserve(db, task)
    task.status = TaskStatus.OUTLINE_GENERATED
    task.outline_confirmed = False
    task.error = None
    task.progress = "请调整大纲或写作要求后重新提交"
    db.commit()
    db.refresh(task)
    return task


@router.post("/task/{task_id}/confirm-outline", response_model=TaskResp, summary="人工介入点2：确认大纲 + 正文写作配置 + 配图方式")
def confirm_outline(task_id: int, req: ConfirmOutlineReq, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """用户确认大纲，可传入修改后的大纲，同时保存正文写作配置（字数/水平/额外要求）和配图方式"""
    task = _get_owned_task(db, task_id, current_user, lock=True)
    _check_not_running(task)
    if task.status != TaskStatus.OUTLINE_GENERATED:
        raise HTTPException(status_code=400, detail="当前状态不允许确认大纲")
    fields = req.model_fields_set
    image_source = req.image_source if "image_source" in fields else task.image_source
    if task.need_image and image_source not in ("api", "ai"):
        raise HTTPException(status_code=400, detail="需要配图时，image_source 必须是 api 或 ai")
    if not (req.outline if req.outline is not None else task.outline or "").strip():
        raise HTTPException(status_code=400, detail="请填写大纲后再确认")

    TaskService.confirm_outline(
        db, task_id,
        outline=req.outline,
        word_count=req.word_count if "word_count" in fields else task.word_count,
        level=req.level if "level" in fields else task.level,
        content_extra_requirements=(req.content_extra_requirements if "content_extra_requirements" in fields
                                    else task.content_extra_requirements),
        image_source=image_source if task.need_image else None,
    )
    return TaskService.get_task(db, task_id)


# ========== 节点3：生成正文 ==========

@router.post("/task/{task_id}/generate-content", response_model=TaskResp, summary="节点3：生成正文")
def generate_content(task_id: int, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user), key: IdempotencyKey = None):
    """根据已确认的大纲，后台异步生成正文（含审稿打回循环），支持重新生成"""
    task, replay = _submission(db, task_id, current_user, key, "generate-content")
    if replay is not None:
        return replay
    _check_not_running(task)
    if task.status not in (TaskStatus.OUTLINE_GENERATED, TaskStatus.FAILED,
                           TaskStatus.CONTENT_GENERATED, TaskStatus.COMPLETED) or not task.outline_confirmed:
        raise HTTPException(status_code=400, detail="请先确认大纲")
    if task.content or task.formatted_content or task.content_research or task.writing_thoughts:
        manuscript_recovery.preserve(db, task)
    _reset_content(task)
    return _start_stage(db, task, "content", TaskStatus.RESEARCHING_CONTENT, "正文写作任务已排队")


@router.post("/task/{task_id}/restore-previous", response_model=TaskResp, summary="免费恢复生成失败前的稿件")
def restore_previous(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = _get_owned_task(db, task_id, current_user, lock=True)
    if task.status != TaskStatus.FAILED:
        raise HTTPException(409, detail="仅在本次生成失败后可恢复上一版稿件")
    backup = db.get(ManuscriptBackup, task_id)
    if backup is None:
        raise HTTPException(409, detail="没有可恢复的上一版稿件")
    manuscript_recovery.restore(db, task, backup)
    db.commit()
    return _get_owned_snapshot(db, task_id, current_user)


# ========== 博客详情 ==========

@router.get("/blog/{task_id}", summary="查询博客详情（作者本人）")
def get_blog_detail(task_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """任务完成后，作者本人查询完整博客内容（含调研、思路、审稿等过程数据）"""
    task = _get_owned_task(db, task_id, current_user)
    if task.status not in (TaskStatus.CONTENT_GENERATED, TaskStatus.COMPLETED):
        raise HTTPException(status_code=400, detail="任务尚未完成，无法查看博客详情")

    content = task.formatted_content or task.content
    return {
        "task_id": task.id,
        "progress": task.progress,
        "revision": task.revision,
        "purpose": task.purpose,
        "evidence_sources": task.evidence_sources or [],
        "topic": task.topic,
        "selected_title": task.selected_title,
        "outline": task.outline,
        "title_research": task.title_research,
        "outline_research": task.outline_research,
        "content_research": task.content_research,
        "writing_thoughts": task.writing_thoughts,
        "target_word_count": task.word_count,
        "level": task.level,
        "extra_requirements": task.extra_requirements,
        "content_extra_requirements": task.content_extra_requirements,
        "article_style": task.article_style,
        "article_style_custom": task.article_style_custom,
        "need_image": task.need_image,
        "image_source": task.image_source,
        "content": content,
        "formatted_content": task.formatted_content,
        "image_prompts": TaskService.parse_image_prompts(task.image_prompts),
        "image_urls": TaskService.parse_image_urls(task.image_urls),
        "review_result": TaskService.parse_review_result(task.review_feedback),
        "is_public": task.is_public,
        "allow_download": task.allow_download,
        "download_price": float(task.download_price or 0),
        "word_count": count_chars(content) if content else 0,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }
