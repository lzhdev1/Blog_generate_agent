"""Durable generation requests. A task may have only one outstanding stage."""
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, false, func, text

from src.blog_agent.db.session import Base


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        CheckConstraint("stage IN ('title', 'outline', 'content')"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')"),
        Index("ix_generation_job_claim", "status", "lease_until", "id"),
        Index("ix_generation_job_user_status", "user_id", "status"),
        Index("ix_generation_job_task_id", "task_id", "id"),
        Index(
            "uq_generation_job_active_task", "task_id", unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("blog_task.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String(12), nullable=False)
    review_only = Column(Boolean, nullable=False, server_default=false(), default=False)
    status = Column(String(12), nullable=False, default="queued")
    attempt = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False)
    token = Column(String(32))
    lease_until = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))


class GenerationRequest(Base):
    """Receipt for one accepted HTTP command. Its transaction also creates the job."""
    __tablename__ = "generation_requests"

    task_id = Column(Integer, ForeignKey("blog_task.id", ondelete="CASCADE"), primary_key=True)
    key_hash = Column(String(64), primary_key=True)
    command_hash = Column(String(64), nullable=False)


class GenerationReservation(Base):
    """Refundable daily quota, retained only until this job starts executing."""
    __tablename__ = "generation_reservations"
    __table_args__ = (CheckConstraint("units > 0"),)

    job_id = Column(Integer, ForeignKey("generation_jobs.id", ondelete="CASCADE"), primary_key=True)
    window = Column(BigInteger, nullable=False)
    units = Column(Integer, nullable=False)
