"""Authorize each local illustration using the task that generated its filename."""
import re

from sqlalchemy import select

from src.blog_agent.db.access_models import SavedMedia
from src.blog_agent.db.models import BlogTask, DownloadRecord, Purchase, TaskStatus
from src.blog_agent.service.quota_service import insert_for

NAME = re.compile(r"task([1-9][0-9]{0,9})_[a-zA-Z0-9_-]{1,100}\.(?:png|jpe?g|webp|gif|avif)")
LOCAL_IMAGE = re.compile(r"/images/(" + NAME.pattern + r")(?=[)\s\"'<>?#\]]|$)")


def names_for(task_id, content):
    return {m.group(1) for m in LOCAL_IMAGE.finditer(content or "") if int(m.group(2)) == task_id}


def preserve_snapshot_media(db, task_ids):
    """Keep grants for old snapshots before the original FK is detached."""
    if not task_ids:
        return
    for model in (Purchase, DownloadRecord):
        records = db.query(model.user_id, model.task_id, model.content_snapshot).filter(model.task_id.in_(task_ids))
        for user_id, task_id, content in records.yield_per(50):
            for filename in names_for(task_id, content):
                stmt = insert_for(db, SavedMedia).values(user_id=user_id, filename=filename)
                db.execute(stmt.on_conflict_do_nothing(index_elements=["user_id", "filename"]))


def can_view_media(db, viewer_id, filename):
    match = NAME.fullmatch(filename)
    if not match or int(match[1]) > 2147483647:
        return False
    task_id = int(match[1])
    task = db.get(BlogTask, task_id)
    if task:
        finished = task.status in (TaskStatus.COMPLETED, TaskStatus.CONTENT_GENERATED)
        owner = viewer_id is not None and task.user_id == viewer_id
        if owner or (finished and (task.is_public or task.is_demo)):
            if any(filename in names_for(task_id, field)
                   for field in (task.image_urls, task.formatted_content, task.content)):
                return True
    if viewer_id is None:
        return False
    if db.get(SavedMedia, (viewer_id, filename)):
        return True
    for model in (DownloadRecord, Purchase):
        content = db.scalar(select(model.content_snapshot).where(model.user_id == viewer_id, model.task_id == task_id))
        if filename in names_for(task_id, content):
            return True
    return False
