"""Preserve the author's previous work in the same transaction as a rewrite."""
from src.blog_agent.db.models import ManuscriptBackup, TaskStatus


# Publication, price and ownership are deliberately not part of an editorial copy.
FIELDS = (
    "status", "progress", "error", "titles", "title_scores", "title_research", "selected_title",
    "article_style", "article_style_custom", "need_image", "image_source", "extra_requirements",
    "outline", "outline_research", "outline_confirmed", "word_count", "level", "content_extra_requirements",
    "content_research", "writing_thoughts", "content", "review_feedback", "formatted_content",
    "image_prompts", "image_urls", "evidence_sources", "purpose",
)


def preserve(db, task):
    # The caller holds the task row lock. Keep a finished edition across failed
    # retries. When only partial work exists, prefer the latest written draft.
    backup = db.get(ManuscriptBackup, task.id)
    if backup is None:
        backup = ManuscriptBackup(task_id=task.id)
        db.add(backup)
    elif not (backup.manuscript["status"] == TaskStatus.FAILED and task.status == TaskStatus.FAILED and task.content):
        return
    backup.manuscript = {name: getattr(task, name) for name in FIELDS}


def restore(db, task, backup):
    for name in FIELDS:
        if name in backup.manuscript:
            setattr(task, name, backup.manuscript[name])
    task.status = TaskStatus(task.status)
    task.is_public = task.allow_download = False
    task.download_price = 0
    db.delete(backup)
