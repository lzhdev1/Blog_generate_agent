import json
from typing import List, Optional

from sqlalchemy.orm import Session

from src.blog_agent.db.models import BlogTask, TaskStatus
from src.blog_agent.db.repositories.task_repo import TaskRepository


class TaskService:
    """任务业务逻辑层：调用 repo 操作数据库，做业务处理"""

    # ========== 基础查询 ==========

    @staticmethod
    def create_task(db: Session, topic: str) -> BlogTask:
        """创建博客生成任务"""
        return TaskRepository.create_task(db, topic=topic)

    @staticmethod
    def get_task(db: Session, task_id: int) -> Optional[BlogTask]:
        """根据ID查询任务"""
        return TaskRepository.get_task_by_id(db, task_id=task_id)

    @staticmethod
    def delete_task(db: Session, task_id: int) -> bool:
        """根据ID删除任务"""
        return TaskRepository.delete_task(db, task_id=task_id)

    @staticmethod
    def list_tasks(db: Session, limit: int = 20, offset: int = 0):
        """任务列表（简单分页）"""
        total = db.query(BlogTask).count()
        items = (
            db.query(BlogTask)
            .order_by(BlogTask.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return total, items

    # ========== 通用：状态和进度 ==========

    @staticmethod
    def update_status(db: Session, task_id: int, status: TaskStatus):
        """更新任务状态"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if task:
            task.status = status
            db.commit()

    @staticmethod
    def update_progress(db: Session, task_id: int, progress: str):
        """更新当前执行进度提示"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if task:
            task.progress = progress
            db.commit()

    # ========== 调研节点 ==========

    @staticmethod
    def save_title_research(db: Session, task_id: int, research: str):
        """保存标题调研结果"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if task:
            task.title_research = research
            db.commit()

    @staticmethod
    def save_outline_research(db: Session, task_id: int, research: str):
        """保存大纲调研结果"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if task:
            task.outline_research = research
            db.commit()

    @staticmethod
    def save_content_research(db: Session, task_id: int, research: str):
        """保存正文调研结果"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if task:
            task.content_research = research
            db.commit()

    # ========== 节点1：标题 ==========

    @staticmethod
    def save_titles(db: Session, task_id: int, titles: List[str]):
        """保存生成的3个标题，状态改为 title_generated"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if not task:
            return
        task.titles = json.dumps(titles, ensure_ascii=False)
        task.status = TaskStatus.TITLE_GENERATED
        task.progress = "标题已生成，请选择标题并配置配图需求"
        db.commit()

    @staticmethod
    def save_title_scores(db: Session, task_id: int, scores: list):
        """保存标题评分结果"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if not task:
            return
        task.title_scores = json.dumps(scores, ensure_ascii=False)
        db.commit()

    @staticmethod
    def select_title_and_config(
        db: Session,
        task_id: int,
        selected_title: str,
        need_image: bool,
        image_source: Optional[str] = None,
    ):
        """用户选择标题 + 配置配图需求"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if not task:
            return
        task.selected_title = selected_title
        task.need_image = need_image
        task.image_source = image_source
        db.commit()

    # ========== 节点2：大纲 ==========

    @staticmethod
    def save_outline(db: Session, task_id: int, outline: str):
        """保存生成的大纲，状态改为 outline_generated"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if not task:
            return
        task.outline = outline
        task.outline_confirmed = False
        task.status = TaskStatus.OUTLINE_GENERATED
        task.progress = "大纲已生成，请确认或修改"
        db.commit()

    @staticmethod
    def confirm_outline(db: Session, task_id: int, outline: Optional[str] = None):
        """用户确认大纲，可传入修改后的大纲"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if not task:
            return
        if outline is not None:
            task.outline = outline
        task.outline_confirmed = True
        task.progress = "大纲已确认，准备生成正文..."
        db.commit()

    # ========== 节点3：正文 ==========

    @staticmethod
    def save_content(db: Session, task_id: int, content: str):
        """保存生成的正文，状态改为 content_generated"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if not task:
            return
        task.content = content
        task.status = TaskStatus.CONTENT_GENERATED
        task.progress = "正文已生成"
        db.commit()

    # ========== 审稿节点 ==========

    @staticmethod
    def save_review_feedback(db: Session, task_id: int, feedback: str, passed: bool):
        """保存审稿意见"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if not task:
            return
        task.review_feedback = feedback
        db.commit()

    # ========== 配图节点 ==========

    @staticmethod
    def save_image_urls(db: Session, task_id: int, image_urls: List[str]):
        """保存配图URL列表"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if not task:
            return
        task.image_urls = json.dumps(image_urls, ensure_ascii=False)
        db.commit()

    # ========== 格式化节点 ==========

    @staticmethod
    def save_formatted_content(db: Session, task_id: int, content: str):
        """保存格式化后的正文，标记为完成"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if not task:
            return
        task.formatted_content = content
        task.status = TaskStatus.COMPLETED
        task.progress = "全部完成"
        db.commit()

    # ========== 失败处理 ==========

    @staticmethod
    def mark_failed(db: Session, task_id: int, error: str):
        """标记任务失败，写入错误信息"""
        task = TaskRepository.get_task_by_id(db, task_id)
        if task:
            task.error = error
            task.status = TaskStatus.FAILED
            task.progress = f"执行失败：{error[:50]}"
            db.commit()

    # ========== 工具方法 ==========

    @staticmethod
    def parse_titles(titles_str: Optional[str]) -> List[str]:
        """把数据库存的标题 JSON 字符串解析成列表"""
        if not titles_str:
            return []
        try:
            return json.loads(titles_str)
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def parse_image_urls(image_urls_str: Optional[str]) -> List[str]:
        """把数据库存的图片URL JSON 字符串解析成列表"""
        if not image_urls_str:
            return []
        try:
            return json.loads(image_urls_str)
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def parse_image_prompts(image_prompts_str: Optional[str]) -> List[str]:
        """把数据库存的配图提示词 JSON 字符串解析成列表"""
        if not image_prompts_str:
            return []
        try:
            return json.loads(image_prompts_str)
        except (json.JSONDecodeError, TypeError):
            return []
