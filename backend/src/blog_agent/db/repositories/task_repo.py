import json
from sqlalchemy.orm import Session

from src.blog_agent.db.models import BlogTask, TaskStatus


class TaskRepository:

    @staticmethod
    def create_task(db: Session, topic: str) -> BlogTask:
        task = BlogTask(topic=topic)
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def get_task_by_id(db: Session, task_id: int) -> BlogTask | None:
        return db.query(BlogTask).filter(BlogTask.id == task_id).first()

    @staticmethod
    def update_task_status(db: Session, task_id: int, status: TaskStatus):
        task = TaskRepository.get_task_by_id(db, task_id)
        if task:
            task.status = status
            db.commit()

    @staticmethod
    def update_task_result(
        db: Session,
        task_id: int,
        outline: str | None = None,
        content: str | None = None,
        image_prompts: list[str] | None = None,
        error: str | None = None
    ):
        task = TaskRepository.get_task_by_id(db, task_id)
        if not task:
            return
        if outline is not None:
            task.outline = outline
        if content is not None:
            task.content = content
        if image_prompts is not None:
            task.image_prompts = json.dumps(image_prompts, ensure_ascii=False)
        if error is not None:
            task.error = error
        db.commit()
