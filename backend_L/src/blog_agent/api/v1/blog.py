"""任务/博客 API（鉴权版：登录才能发起生成任务，作者本人管理自己的任务）

流程与旧版对齐：
create（需登录）→ generate-titles（后台跑标题阶段）→ 轮询/SSE 到 title_generated
→ submit-title-config（后台跑大纲阶段）→ 轮询/SSE 到 outline_generated
→ confirm-outline（保存正文配置）→ generate-content（后台跑正文阶段）→ 轮询/SSE 到 content_generated
→ GET /blog/{id} 查看完整产物（仅作者本人）
→ PUT /task/{id}/visibility 配置公开/下载/价格
"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from src.blog_agent.api.deps import get_current_user, get_db
from src.blog_agent.db.models import TaskStatus, User
from src.blog_agent.schemas.task_schema import (
    ConfirmOutlineReq,
    TaskCreateReq,
    TaskListResp,
    TaskResp,
    TitleAndConfigReq,
    VisibilityReq,
)
from src.blog_agent.service import agent_service
from src.blog_agent.service.task_service import TaskService

router = APIRouter(prefix="/api/v1", tags=["博客任务"])

# 正在执行中的状态（后端任务未结束，接口直接返回当前状态）
_RUNNING_STATUSES = {
    TaskStatus.RESEARCHING_TITLE, TaskStatus.GENERATING_TITLES,
    TaskStatus.RESEARCHING_OUTLINE, TaskStatus.GENERATING_OUTLINE,
    TaskStatus.RESEARCHING_CONTENT, TaskStatus.GENERATING_CONTENT,
    TaskStatus.REVIEWING,
}


def _get_owned_task(db: Session, task_id: int, user: User):
    """查询任务并校验归属：非本人任务（非 demo）一律拒绝"""
    task = TaskService.get_task(db, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.is_demo or task.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该任务")
    return task


def _check_not_running(db: Session, task: object) -> None:
    """任务正在后台执行时，不允许重复触发"""
    if task.status in _RUNNING_STATUSES:
        raise HTTPException(status_code=400, detail="任务正在执行中，请稍候")


# ========== 基础接口 ==========

@router.post("/task", response_model=TaskResp, summary="创建博客生成任务（需登录）")
def create_task(req: TaskCreateReq, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    """创建一个博客生成任务，状态为 pending，归属当前用户"""
    task = TaskService.create_task(db, topic=req.topic, user_id=current_user.id)
    return task


@router.get("/task/{task_id}", response_model=TaskResp, summary="查询任务状态")
def get_task(task_id: int, db: Session = Depends(get_db),
             current_user: User = Depends(get_current_user)):
    """根据 task_id 查询任务状态（前端轮询兜底用，包含实时进度）"""
    return _get_owned_task(db, task_id, current_user)


# 终态集合：推送后 SSE 自动断开
_TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED}


@router.get("/task/{task_id}/stream", summary="任务状态 SSE 推送（替代高频轮询）")
async def stream_task_status(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """服务端推送任务状态变化，替代前端 2s 轮询。

    设计要点：
    1. 前置归属校验（与 GET /task/{id} 同规则，非法访问直接 401/403/404）
    2. 状态或进度文本变化才推送（同值不推，省带宽）
    3. DB 查询放线程池（run_in_threadpool），不阻塞事件循环
    4. 终态（completed/failed）推送后自动断开；客户端断开（关页面/跳转）即停止
    5. X-Accel-Buffering: no 防止 Nginx 缓冲 SSE（生产部署关键）
    """
    # 归属校验：非法访问在这里直接返回错误响应（不进 generator）
    _get_owned_task(db, task_id, current_user)

    async def event_generator():
        from src.blog_agent.db.session import SessionLocal

        def _fetch():
            """线程池内执行：独立 session 查询任务状态（线程安全）"""
            s = SessionLocal()
            try:
                t = TaskService.get_task(s, task_id=task_id)
                return {
                    "status": t.status if t else None,
                    "progress": t.progress if t else None,
                    "error": t.error if t else None,
                }
            finally:
                s.close()

        last_sig: tuple | None = None
        while True:
            # 客户端已断开（关页面/组件卸载/跳转）→ 停止推送
            if await request.is_disconnected():
                break
            payload = await run_in_threadpool(_fetch)
            if payload["status"] is None:
                yield "event: error\ndata: {\"detail\":\"任务不存在\"}\n\n"
                break
            sig = (payload["status"], payload["progress"])
            if sig != last_sig:
                last_sig = sig
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if payload["status"] in _TERMINAL_STATUSES:
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
    _get_owned_task(db, task_id, current_user)
    TaskService.delete_task(db, task_id=task_id)
    return {"message": "删除成功", "task_id": task_id}


@router.get("/task", response_model=TaskListResp, summary="我的任务列表")
def list_tasks(
    limit: int = 20,
    offset: int = 0,
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
    task = _get_owned_task(db, task_id, current_user)
    if task.status not in (TaskStatus.CONTENT_GENERATED, TaskStatus.COMPLETED):
        raise HTTPException(status_code=400, detail="任务未完成，暂不能配置公开/下载")
    task.is_public = req.is_public
    task.allow_download = req.allow_download
    task.download_price = req.download_price
    db.commit()
    db.refresh(task)
    return task


# ========== 节点1：调研 + 生成标题 ==========

@router.post("/task/{task_id}/generate-titles", response_model=TaskResp, summary="节点1：调研并生成标题（支持重新生成）")
def generate_titles(task_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """先调研同类文章标题，再生成3个标题（异步执行，轮询 GET /task/{id} 看进度）"""
    task = _get_owned_task(db, task_id, current_user)
    allowed = (TaskStatus.PENDING, TaskStatus.TITLE_GENERATED, TaskStatus.FAILED,
               TaskStatus.OUTLINE_GENERATED, TaskStatus.CONTENT_GENERATED, TaskStatus.COMPLETED)
    if task.status not in allowed:
        _check_not_running(db, task)
        raise HTTPException(status_code=400, detail="当前状态不允许生成标题")

    # 重新生成/失败重试时，清空旧标题与配置
    if task.status != TaskStatus.PENDING:
        task.titles = None
        task.title_scores = None
        task.title_research = None
        task.selected_title = None
        task.need_image = False
        task.image_source = None
        task.article_style = None
        task.article_style_custom = None
        task.extra_requirements = None
        task.error = None
        task.status = TaskStatus.PENDING
        db.commit()

    agent_service.start_title_stage(task_id, task.topic)
    return TaskService.get_task(db, task_id)


# ========== 人工介入点1：选择标题 + 配图配置，自动开始大纲调研和生成 ==========

@router.post("/task/{task_id}/submit-title-config", response_model=TaskResp, summary="人工介入点1：选择标题+是否配图+文章风格，自动生成大纲")
def submit_title_config(task_id: int, req: TitleAndConfigReq, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    """用户选择标题，配置是否配图、文章风格、对大纲的额外要求；提交后异步开始大纲阶段"""
    task = _get_owned_task(db, task_id, current_user)
    if task.status != TaskStatus.TITLE_GENERATED:
        raise HTTPException(status_code=400, detail="当前状态不允许选择标题")
    if req.article_style == "custom" and not req.article_style_custom:
        raise HTTPException(status_code=400, detail="选择自定义风格时，必须填写自定义风格内容")

    agent_service.start_outline_stage(
        task_id,
        selected_title=req.title,
        need_image=req.need_image,
        article_style=req.article_style,
        article_style_custom=req.article_style_custom,
        extra_requirements=req.extra_requirements,
    )
    return TaskService.get_task(db, task_id)


@router.post("/task/{task_id}/regenerate-outline", response_model=TaskResp, summary="重新生成大纲")
def regenerate_outline(task_id: int, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    """对大纲不满意时，重新生成大纲（使用已保存的标题、配图、风格配置）"""
    task = _get_owned_task(db, task_id, current_user)
    if task.status != TaskStatus.OUTLINE_GENERATED:
        raise HTTPException(status_code=400, detail="当前状态不允许重新生成大纲")
    if not task.selected_title:
        raise HTTPException(status_code=400, detail="未找到已选择的标题")

    agent_service.start_outline_stage(
        task_id,
        selected_title=task.selected_title,
        need_image=task.need_image,
        article_style=task.article_style,
        article_style_custom=task.article_style_custom,
        extra_requirements=task.extra_requirements,
    )
    return TaskService.get_task(db, task_id)


# ========== 人工介入点2：确认大纲 ==========

@router.post("/task/{task_id}/confirm-outline", response_model=TaskResp, summary="人工介入点2：确认大纲 + 正文写作配置 + 配图方式")
def confirm_outline(task_id: int, req: ConfirmOutlineReq, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    """用户确认大纲，可传入修改后的大纲，同时保存正文写作配置（字数/水平/额外要求）和配图方式"""
    task = _get_owned_task(db, task_id, current_user)
    if task.status != TaskStatus.OUTLINE_GENERATED:
        raise HTTPException(status_code=400, detail="当前状态不允许确认大纲")
    if task.need_image and req.image_source not in ("api", "ai"):
        raise HTTPException(status_code=400, detail="需要配图时，image_source 必须是 api 或 ai")

    TaskService.confirm_outline(
        db, task_id,
        outline=req.outline,
        word_count=req.word_count,
        level=req.level,
        content_extra_requirements=req.content_extra_requirements,
        image_source=req.image_source,
    )
    return TaskService.get_task(db, task_id)


# ========== 节点3：生成正文 ==========

@router.post("/task/{task_id}/generate-content", response_model=TaskResp, summary="节点3：生成正文")
def generate_content(task_id: int, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    """根据已确认的大纲，后台异步生成正文（含审稿打回循环），支持重新生成"""
    task = _get_owned_task(db, task_id, current_user)
    if not task.outline_confirmed:
        raise HTTPException(status_code=400, detail="请先确认大纲")
    _check_not_running(db, task)

    # 失败或已完成都允许重新执行
    if task.status in (TaskStatus.FAILED, TaskStatus.COMPLETED, TaskStatus.CONTENT_GENERATED):
        TaskService.update_status(db, task_id, TaskStatus.OUTLINE_GENERATED)

    agent_service.start_content_stage(task_id)
    return TaskService.get_task(db, task_id)


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
        "word_count": len(content) if content else 0,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }
