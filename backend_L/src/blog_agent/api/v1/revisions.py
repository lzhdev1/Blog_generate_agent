"""Author-only private edits, bound to the manuscript the author actually reviewed."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.blog_agent.api.deps import get_current_user, get_db
from src.blog_agent.api.v1.blog import IdempotencyKey, _check_not_running, _get_owned_task, _submission
from src.blog_agent.db.models import EditorialDraft, ManuscriptBackup, TaskStatus, User
from src.blog_agent.schemas.task_schema import DraftApplyReq, DraftSaveReq, DraftVersionReq, EditorialDraftResp, TaskResp
from src.blog_agent.service import job_queue
from src.blog_agent.service.task_service import TaskService

router = APIRouter(prefix="/api/v1/task/{task_id}/revision", tags=["文稿修订"])
BUSY = {"queued", "reviewing"}


def _expect_base(task, revision):
    if revision != task.revision:
        raise HTTPException(409, "原稿已更新，请查看当前版本后重新编辑")


def _expect_version(draft, version):
    if not draft or draft.version != version:
        raise HTTPException(409, "修订稿已更新，请重新载入后核对")


@router.get("", response_model=EditorialDraftResp | None)
def get_revision(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _get_owned_task(db, task_id, user)
    draft = db.get(EditorialDraft, task_id)
    return draft if draft and draft.status != "applied" else None


@router.put("", response_model=EditorialDraftResp)
def save_revision(task_id: int, req: DraftSaveReq, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = _get_owned_task(db, task_id, user, lock=True)
    _check_not_running(task)
    if task.status not in (TaskStatus.COMPLETED, TaskStatus.CONTENT_GENERATED, TaskStatus.FAILED) or not (task.content or task.formatted_content):
        raise HTTPException(409, "稿件产生正文后可以局部修订")
    _expect_base(task, req.expected_revision)
    content = req.content
    if not content.strip():
        raise HTTPException(422, "请填写正文")
    draft = db.get(EditorialDraft, task_id, with_for_update=True)
    query = (req.source_query or "").strip() or None
    if draft and draft.status != "applied":
        _expect_version(draft, req.expected_version)
        _expect_base(task, draft.base_revision)
        if draft.content == content and draft.source_query == query:
            return draft
        if draft.status in BUSY:
            raise HTTPException(409, "当前修订正在审核，请等待结果")
    else:
        if req.expected_version != 0:
            raise HTTPException(409, "修订稿已应用或删除，请重新载入")
        if draft is None:
            draft = EditorialDraft(task_id=task_id)
            db.add(draft)
        draft.evidence_sources = task.evidence_sources or []
    task.editorial_version += 1
    draft.version, draft.content, draft.base_revision = task.editorial_version, content, task.revision
    draft.source_query = query
    draft.status, draft.review_result, draft.error, draft.job_id = "draft", None, None, None
    db.commit()
    return draft


@router.post("/review", response_model=EditorialDraftResp)
def submit_review(task_id: int, req: DraftVersionReq, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user), key: IdempotencyKey = None):
    if not key:
        raise HTTPException(422, "提交复审需要 Idempotency-Key，以便断线重试时识别本次扣点")
    task, replay = _submission(db, task_id, user, key, "review-revision", req.model_dump())
    if replay is not None:
        task = _get_owned_task(db, task_id, user, lock=True)
    draft = db.get(EditorialDraft, task_id, with_for_update=True)
    _expect_version(draft, req.expected_version)
    _expect_base(task, draft.base_revision)
    _check_not_running(task)
    if draft.status == "applied":
        raise HTTPException(409, "修订已采用，请从当前稿件开始新的修订")
    if replay is not None or draft.status in {"approved", "rejected"}:
        return draft
    if draft.status in BUSY:
        # Another tab accepted the same version. Its caller can replay this key
        # after a worker failure without accidentally starting a second paid attempt.
        db.commit()
        return draft
    job = job_queue.enqueue(db, task, "revision")
    draft.status, draft.job_id, draft.review_result, draft.error = "queued", job.id, None, None
    db.commit()
    return draft


@router.post("/apply", response_model=TaskResp)
def apply_revision(task_id: int, req: DraftApplyReq, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = _get_owned_task(db, task_id, user, lock=True)
    _check_not_running(task)
    draft = db.get(EditorialDraft, task_id, with_for_update=True)
    _expect_version(draft, req.expected_version)
    if draft.status == "applied" and draft.base_revision == req.expected_revision and task.formatted_content == draft.content:
        return task
    _expect_base(task, req.expected_revision)
    _expect_base(task, draft.base_revision)
    if draft.status != "approved" or not (draft.review_result or {}).get("passed"):
        raise HTTPException(409, "请先完成这一版修订的审核")
    task.content = task.formatted_content = draft.content
    task.evidence_sources = draft.evidence_sources or []
    task.image_urls = json.dumps([url for url in TaskService.parse_image_urls(task.image_urls)
                                  if url in draft.content])
    task.image_prompts = task.writing_thoughts = None
    task.review_feedback = json.dumps(draft.review_result, ensure_ascii=False)
    task.status, task.progress, task.error = TaskStatus.COMPLETED, "修订已采用，请确认发布设置", None
    task.is_public, task.allow_download, task.download_price = False, False, 0
    db.query(ManuscriptBackup).filter_by(task_id=task_id).delete(synchronize_session=False)
    draft.status = "applied"
    db.commit()
    return task


@router.delete("")
def discard_revision(task_id: int, expected_version: int = Query(ge=1), db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    _get_owned_task(db, task_id, user, lock=True)
    draft = db.get(EditorialDraft, task_id, with_for_update=True)
    _expect_version(draft, expected_version)
    if draft.status in BUSY:
        raise HTTPException(409, "正在审核的修订暂不能丢弃")
    db.delete(draft)
    db.commit()
    return {"discarded": True}
