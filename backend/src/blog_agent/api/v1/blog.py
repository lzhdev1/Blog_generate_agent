from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.blog_agent.api.deps import get_db
from src.blog_agent.db.models import TaskStatus
from src.blog_agent.schemas.task_schema import (
    TaskCreateReq,
    TaskResp,
    TaskListResp,
    TitleAndConfigReq,
    ConfirmOutlineReq,
)
from src.blog_agent.schemas.blog_schema import BlogDetailResp
from src.blog_agent.service.task_service import TaskService
from src.blog_agent.agent.graph import (
    run_generate_titles,
    run_generate_outline,
    run_generate_content,
)

router = APIRouter(prefix="/api/v1", tags=["博客任务"])


# ========== 基础接口 ==========

@router.post("/task", response_model=TaskResp, summary="创建博客生成任务")
def create_task(req: TaskCreateReq, db: Session = Depends(get_db)):
    """创建一个博客生成任务，状态为 pending"""
    task = TaskService.create_task(db, topic=req.topic)
    return task


@router.get("/task/{task_id}", response_model=TaskResp, summary="查询任务状态")
def get_task(task_id: int, db: Session = Depends(get_db)):
    """根据 task_id 查询任务状态（前端轮询用，包含实时进度）"""
    task = TaskService.get_task(db, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.delete("/task/{task_id}", summary="删除任务")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    """根据 task_id 删除任务及其所有数据"""
    task = TaskService.get_task(db, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    TaskService.delete_task(db, task_id=task_id)
    return {"message": "删除成功", "task_id": task_id}


@router.get("/task", response_model=TaskListResp, summary="任务列表")
def list_tasks(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """分页查询任务列表"""
    total, items = TaskService.list_tasks(db, limit=limit, offset=offset)
    return {"total": total, "items": items}


@router.get("/blog/{task_id}", response_model=BlogDetailResp, summary="查询博客详情")
def get_blog_detail(task_id: int, db: Session = Depends(get_db)):
    """任务完成后，查询完整博客内容"""
    task = TaskService.get_task(db, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in ("content_generated", "completed"):
        raise HTTPException(status_code=400, detail="任务尚未完成，无法查看博客详情")

    content = task.formatted_content or task.content
    return {
        "task_id": task.id,
        "topic": task.topic,
        "selected_title": task.selected_title,
        "outline": task.outline,
        "content": content,
        "formatted_content": task.formatted_content,
        "image_prompts": TaskService.parse_image_prompts(task.image_prompts),
        "image_urls": TaskService.parse_image_urls(task.image_urls),
        "review_feedback": task.review_feedback,
        "word_count": len(content) if content else 0,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


# ========== 节点1：调研 + 生成标题 ==========

@router.post("/task/{task_id}/generate-titles", response_model=TaskResp, summary="节点1：调研并生成标题（支持重新生成）")
def generate_titles(task_id: int, db: Session = Depends(get_db)):
    """
    先调研同类文章标题（避免重复），再生成3个标题
    支持 pending 和 title_generated 状态（重新生成）
    执行过程中可通过 GET /task/{id} 查看实时进度
    """
    task = TaskService.get_task(db, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status not in ("pending", "title_generated"):
        raise HTTPException(status_code=400, detail="当前状态不允许生成标题")

    # 重新生成时，清空旧的标题和配置
    if task.status == "title_generated":
        task.titles = None
        task.selected_title = None
        task.need_image = False
        task.image_source = None
        task.status = TaskStatus.PENDING
        db.commit()

    try:
        run_generate_titles(db, task_id, task.topic)
    except Exception as e:
        TaskService.mark_failed(db, task_id, str(e))
        raise HTTPException(status_code=500, detail=f"生成标题失败：{e}")

    return TaskService.get_task(db, task_id)


# ========== 人工介入点1：选择标题 + 配图配置，自动开始大纲调研和生成 ==========

@router.post("/task/{task_id}/submit-title-config", response_model=TaskResp, summary="人工介入点1：选择标题+配图配置，自动生成大纲")
def submit_title_config(task_id: int, req: TitleAndConfigReq, db: Session = Depends(get_db)):
    """
    用户选择标题，并配置是否需要配图及配图方式
    提交后自动开始：大纲调研 → 生成大纲
    如果需要配图，大纲中会标注配图位置和要求
    """
    task = TaskService.get_task(db, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "title_generated":
        raise HTTPException(status_code=400, detail="当前状态不允许选择标题")
    if req.need_image and req.image_source not in ("api", "ai"):
        raise HTTPException(status_code=400, detail="需要配图时，image_source 必须是 api 或 ai")

    try:
        run_generate_outline(
            db,
            task_id,
            selected_title=req.title,
            need_image=req.need_image,
            image_source=req.image_source,
        )
    except Exception as e:
        TaskService.mark_failed(db, task_id, str(e))
        raise HTTPException(status_code=500, detail=f"生成大纲失败：{e}")

    return TaskService.get_task(db, task_id)


@router.post("/task/{task_id}/regenerate-outline", response_model=TaskResp, summary="重新生成大纲")
def regenerate_outline(task_id: int, db: Session = Depends(get_db)):
    """对大纲不满意时，重新生成大纲（使用已保存的标题和配图配置）"""
    task = TaskService.get_task(db, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "outline_generated":
        raise HTTPException(status_code=400, detail="当前状态不允许重新生成大纲")
    if not task.selected_title:
        raise HTTPException(status_code=400, detail="未找到已选择的标题")

    try:
        run_generate_outline(
            db,
            task_id,
            selected_title=task.selected_title,
            need_image=task.need_image,
            image_source=task.image_source,
        )
    except Exception as e:
        TaskService.mark_failed(db, task_id, str(e))
        raise HTTPException(status_code=500, detail=f"重新生成大纲失败：{e}")

    return TaskService.get_task(db, task_id)


# ========== 人工介入点2：确认大纲 ==========

@router.post("/task/{task_id}/confirm-outline", response_model=TaskResp, summary="人工介入点2：确认大纲")
def confirm_outline(task_id: int, req: ConfirmOutlineReq, db: Session = Depends(get_db)):
    """用户确认大纲，可传入修改后的大纲"""
    task = TaskService.get_task(db, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "outline_generated":
        raise HTTPException(status_code=400, detail="当前状态不允许确认大纲")

    TaskService.confirm_outline(db, task_id, req.outline)
    return TaskService.get_task(db, task_id)


# ========== 节点3：生成正文 ==========

@router.post("/task/{task_id}/generate-content", response_model=TaskResp, summary="节点3：生成正文")
def generate_content(task_id: int, db: Session = Depends(get_db)):
    """根据已确认的大纲，调 LLM 生成正文"""
    task = TaskService.get_task(db, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "outline_generated" or not task.outline_confirmed:
        raise HTTPException(status_code=400, detail="请先确认大纲")

    try:
        run_generate_content(db, task_id)
    except Exception as e:
        TaskService.mark_failed(db, task_id, str(e))
        raise HTTPException(status_code=500, detail=f"生成正文失败：{e}")

    return TaskService.get_task(db, task_id)
