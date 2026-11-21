"""Transactional stage admission, leases and fencing for the PostgreSQL queue."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, event, func, inspect, select
from sqlalchemy.orm import Session

from config.settings import settings
from src.blog_agent.db.job_models import GenerationJob, GenerationReservation
from src.blog_agent.db.models import BlogTask, EditorialDraft, ManuscriptBackup, TaskStatus

ACTIVE = ("queued", "running")
READY = {
    "title": TaskStatus.TITLE_GENERATED,
    "outline": TaskStatus.OUTLINE_GENERATED,
    "content": TaskStatus.COMPLETED,
}
INTERRUPTED = "本阶段执行中断，已保存创作设置。请确认后重新提交。"


@dataclass(frozen=True)
class Claim:
    job_id: int
    token: str


class LeaseLost(Exception):
    """The worker no longer owns the right to write this attempt."""


_writing_claim = ContextVar("generation_job_claim", default=None)


def queue_lock(db: Session, *, wait=True):
    # A short transaction lock, shared by all application replicas in this database.
    if db.get_bind().dialect.name == "postgresql":
        if not wait:
            return db.scalar(select(func.pg_try_advisory_xact_lock(1145849671, 1)))
        db.execute(select(func.pg_advisory_xact_lock(1145849671, 1)))
    return True


def _now(db: Session):
    clock = func.clock_timestamp() if db.get_bind().dialect.name == "postgresql" else func.current_timestamp()
    return db.scalar(select(clock))


def active_jobs(db: Session, user_id: int) -> int:
    return db.query(GenerationJob).filter(
        GenerationJob.user_id == user_id, GenerationJob.status.in_(ACTIVE),
    ).count()


def _check_capacity(db, task):
    total, user_active, task_active = db.execute(
        select(func.count(), func.count().filter(GenerationJob.user_id == task.user_id),
               func.count().filter(GenerationJob.task_id == task.id))
        .select_from(GenerationJob).where(GenerationJob.status.in_(ACTIVE))
    ).one()
    if task_active:
        raise HTTPException(409, "该任务已经在队列中")
    if user_active >= settings.free_max_active_jobs:
        raise HTTPException(429, {"code": "active_job_limit", "message": "你已有任务在排队或生成，请等待该阶段结束后重试"},
                            headers={"Retry-After": "15"})
    if total >= settings.agent_max_queued_jobs:
        raise HTTPException(503, {"code": "queue_full", "message": "生成队列已满，请稍后重试"},
                            headers={"Retry-After": "30"})


def enqueue(db: Session, task: BlogTask, stage: str) -> GenerationJob:
    """Called with the task row locked. The caller commits task, quota and job together."""
    from src.blog_agent.service.quota_service import check_generation_quota, reserve_generation

    if not queue_lock(db, wait=False):
        # Already-full queues and exhausted budgets can reject from committed
        # state without joining the global lock wait behind other manuscripts.
        _check_capacity(db, task)
        check_generation_quota(db, task, stage)
        queue_lock(db)
    _check_capacity(db, task)
    window, units = reserve_generation(db, task, stage)
    review_only = stage == "revision"
    job = GenerationJob(task_id=task.id, user_id=task.user_id, stage="content" if review_only else stage,
                        review_only=review_only,
                        status="queued", max_attempts=settings.agent_job_max_attempts)
    db.add(job)
    db.flush()
    db.add(GenerationReservation(job_id=job.id, window=window, units=units))
    return job


def job_info(job: GenerationJob | None) -> dict | None:
    if job is None:
        return None
    return {"stage": "revision" if job.review_only else job.stage, "status": job.status,
            "attempt": job.attempt, "max_attempts": job.max_attempts}


def latest_job(db: Session, task_id: int) -> dict | None:
    job = db.query(GenerationJob).filter_by(task_id=task_id).order_by(GenerationJob.id.desc()).first()
    return job_info(job)


def recover_legacy(db: Session, *, apply: bool) -> int:
    """Offline upgrade, only after every pre-queue worker has stopped."""
    ready = [TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.CONTENT_GENERATED, *READY.values()]
    legacy = db.query(BlogTask).filter(BlogTask.status.not_in(ready))
    # The operator may run this command before the first new API process creates its tables.
    if inspect(db.connection()).has_table(GenerationJob.__tablename__):
        has_job = select(GenerationJob.id).where(GenerationJob.task_id == BlogTask.id).exists()
        legacy = legacy.filter(~has_job)
    if not apply:
        return legacy.count()
    return legacy.update(
        {BlogTask.status: TaskStatus.FAILED, BlogTask.progress: INTERRUPTED, BlogTask.error: INTERRUPTED},
        synchronize_session=False,
    )


def _finish(job, status, now):
    job.status, job.finished_at = status, now
    job.token = job.lease_until = None


def _owned(db: Session, claim: Claim):
    job = db.query(GenerationJob).filter_by(id=claim.job_id, token=claim.token, status="running").filter(
        GenerationJob.lease_until > _now(db),
    ).with_for_update().populate_existing().first()
    if not job:
        raise LeaseLost()
    return job


def _interrupt(db, job, task, now):
    draft = db.get(EditorialDraft, task.id, with_for_update=True) if job.review_only else None
    if job.started_at is None and job.attempt < job.max_attempts:
        job.status = "queued"
        job.token = job.lease_until = None
        if not job.review_only:
            task.progress = "工作进程未启动，已重新排队"
        return
    _finish(job, "failed", now)
    message = INTERRUPTED
    if job.started_at is None:
        reservation = db.execute(delete(GenerationReservation).where(
            GenerationReservation.job_id == job.id,
        ).returning(GenerationReservation.window, GenerationReservation.units)).one_or_none()
        if reservation:
            from src.blog_agent.service.quota_service import refund_generation
            refund_generation(db, job.user_id, reservation.window, reservation.units)
            message = "本阶段未能启动，已退回原扣点日的额度。请重试。"
    if job.review_only:
        if draft and draft.job_id == job.id:
            draft.status, draft.error = "failed", message
    else:
        task.status = TaskStatus.FAILED
        task.error = task.progress = message


def claim_next(db: Session) -> Claim | None:
    """Recover expired attempts and claim the oldest queued stage; caller commits."""
    queue_lock(db)
    now = _now(db)
    expired = db.query(GenerationJob).filter(
        GenerationJob.status == "running", GenerationJob.lease_until <= now,
    ).order_by(GenerationJob.lease_until).limit(32).with_for_update(skip_locked=True)
    for job in expired:
        # Avoid waiting on a task that is currently being edited/deleted in the API.
        task = db.query(BlogTask).filter_by(id=job.task_id).with_for_update(skip_locked=True).first()
        if task:
            _interrupt(db, job, task, now)
    db.flush()
    if db.query(GenerationJob).filter_by(status="running").count() >= settings.agent_max_workers:
        return None
    job = db.query(GenerationJob).filter_by(status="queued").order_by(
        GenerationJob.id,
    ).with_for_update(skip_locked=True).first()
    if not job:
        return None
    job.status = "running"
    job.attempt += 1
    job.token = uuid4().hex
    job.lease_until = now + timedelta(seconds=settings.agent_job_lease_seconds)
    return Claim(job.id, job.token)


def renew(db: Session, claim: Claim):
    job = _owned(db, claim)
    now = _now(db)
    expires = now + timedelta(seconds=settings.agent_job_lease_seconds)
    if job.started_at:
        deadline = job.started_at + timedelta(seconds=settings.agent_job_max_runtime_seconds)
        expires = min(expires, deadline)
    if expires <= now:
        raise LeaseLost()
    job.lease_until = expires


def abandon(db: Session, claim: Claim):
    """A child exited before a terminal commit. A started stage may have incurred a charge."""
    job = _owned(db, claim)
    task = db.get(BlogTask, job.task_id, with_for_update=True)
    if task:
        _interrupt(db, job, task, _now(db))


def begin_execution(db: Session, claim: Claim) -> tuple[str, tuple]:
    job = _owned(db, claim)
    if job.started_at:
        raise LeaseLost()
    task = db.get(BlogTask, job.task_id)
    if not task:
        raise LeaseLost()
    job.started_at = _now(db)
    # The caller commits both changes before invoking an Agent or provider.
    db.execute(delete(GenerationReservation).where(GenerationReservation.job_id == job.id))
    if job.review_only:
        draft = db.get(EditorialDraft, task.id, with_for_update=True)
        if draft is None or draft.job_id != job.id:
            raise LeaseLost()
        draft.status = "reviewing"
        return "revision", (task.id,)
    args = (task.id,)
    if job.stage == "title":
        args += (task.topic,)
    elif job.stage == "outline":
        args += (task.selected_title, task.need_image, task.article_style, task.article_style_custom, task.extra_requirements)
    return job.stage, args


def finish_editorial_review(db, claim, report, error, sources):
    """Commit the verdict and job completion with the same lease check."""
    job = _owned(db, claim)
    draft = db.get(EditorialDraft, job.task_id, with_for_update=True)
    if not job.review_only or draft is None or draft.job_id != job.id:
        raise LeaseLost()
    draft.review_result, draft.error = report, error
    draft.evidence_sources = sources
    draft.status = "failed" if error else ("approved" if report["passed"] else "rejected")
    _finish(job, "failed" if error else "succeeded", _now(db))


@contextmanager
def fenced_writes(claim: Claim):
    token = _writing_claim.set(claim)
    try:
        yield
    finally:
        _writing_claim.reset(token)


@event.listens_for(Session, "before_flush")
def _fence_agent_writes(db, flush_context, instances):
    """Fence the Agent's existing independent commits using the same database transaction.

    At a checkpoint the job finishes atomically with the visible artifact. A subsequent
    human submission can therefore never overlap writes from the previous attempt.
    """
    claim = _writing_claim.get()
    if claim is None:
        return
    tasks = [row for row in db.dirty if isinstance(row, BlogTask) and db.is_modified(row)]
    if not tasks:
        return
    job = _owned(db, claim)
    for task in tasks:
        if task.id != job.task_id:
            raise LeaseLost()
        if task.status in (TaskStatus.FAILED, READY[job.stage]):
            _finish(job, "failed" if task.status == TaskStatus.FAILED else "succeeded", _now(db))
            if job.status == "succeeded":
                db.query(ManuscriptBackup).filter_by(task_id=task.id).delete(synchronize_session=False)
