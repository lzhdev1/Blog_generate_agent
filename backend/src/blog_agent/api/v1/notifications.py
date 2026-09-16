from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from src.blog_agent.api.deps import get_db, get_current_user
from src.blog_agent.db.models import User, Notification

router = APIRouter(prefix="/api/v1/notifications", tags=["消息通知"])


class NotificationItem(BaseModel):
    id: int
    type: str
    content: str
    task_id: Optional[int] = None
    actor_name: Optional[str] = None
    is_read: bool
    created_at: str

    class Config:
        from_attributes = True


class NotificationListResp(BaseModel):
    total: int
    unread: int
    items: list[NotificationItem]


def _fmt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


@router.get("", response_model=NotificationListResp, summary="通知列表")
def list_notifications(
    limit: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    uid = current_user.id
    total = db.query(Notification).filter(Notification.user_id == uid).count()
    unread = db.query(Notification).filter(Notification.user_id == uid, Notification.is_read.is_(False)).count()
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == uid)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "unread": unread,
        "items": [
            NotificationItem(
                id=n.id,
                type=n.type.value if hasattr(n.type, "value") else str(n.type),
                content=n.content,
                task_id=n.task_id,
                actor_name=n.actor_name,
                is_read=n.is_read,
                created_at=_fmt(n.created_at),
            )
            for n in rows
        ],
    }


@router.get("/unread-count", summary="未读通知数")
def unread_count(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    count = db.query(Notification).filter(
        Notification.user_id == current_user.id, Notification.is_read.is_(False)
    ).count()
    return {"unread": count}


class ReadBody(BaseModel):
    ids: Optional[list[int]] = None  # 不传则全部已读


@router.post("/read", summary="标记已读（指定 id 或全部）")
def mark_read(body: ReadBody, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Notification).filter(Notification.user_id == current_user.id, Notification.is_read.is_(False))
    if body.ids:
        q = q.filter(Notification.id.in_(body.ids))
    updated = q.update({Notification.is_read: True}, synchronize_session=False)
    db.commit()
    return {"updated": updated}


def create_notification(
    db: Session,
    *,
    user_id: int,
    ntype: str,
    content: str,
    task_id: Optional[int] = None,
    actor_name: Optional[str] = None,
) -> Notification:
    """创建站内通知（user_id 为接收者）"""
    n = Notification(
        user_id=user_id,
        type=ntype,
        content=content[:500],
        task_id=task_id,
        actor_name=actor_name,
        is_read=False,
    )
    db.add(n)
    return n
