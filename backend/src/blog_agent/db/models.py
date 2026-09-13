import datetime
from sqlalchemy import Column, Integer, String, Text, Enum, DateTime, Boolean
from enum import StrEnum

from .session import Base


class TaskStatus(StrEnum):
    PENDING = "pending"                          # 任务已创建
    RESEARCHING_TITLE = "researching_title"      # 正在调研（标题）
    GENERATING_TITLES = "generating_titles"      # 正在生成标题+评分
    TITLE_GENERATED = "title_generated"          # 标题已生成，等用户选择+配置
    RESEARCHING_OUTLINE = "researching_outline"  # 正在调研（大纲）
    GENERATING_OUTLINE = "generating_outline"    # 正在生成大纲
    OUTLINE_GENERATED = "outline_generated"      # 大纲已生成，等用户确认
    RESEARCHING_CONTENT = "researching_content"  # 正在调研（正文资料）
    GENERATING_CONTENT = "generating_content"    # 正在生成正文
    REVIEWING = "reviewing"                      # 正在审稿
    CONTENT_GENERATED = "content_generated"      # 正文已生成
    GENERATING_IMAGES = "generating_images"      # 正在生成配图
    FORMATTING = "formatting"                    # 正在格式化
    COMPLETED = "completed"                      # 全部完成
    FAILED = "failed"                            # 执行失败


class BlogTask(Base):
    __tablename__ = "blog_task"

    id = Column(Integer, primary_key=True, index=True)
    topic = Column(String(512), nullable=False, comment="博客主题")
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False)
    progress = Column(String(256), nullable=True, comment="当前执行进度提示")

    # 调研结果
    title_research = Column(Text, nullable=True, comment="标题调研摘要")
    outline_research = Column(Text, nullable=True, comment="大纲调研摘要")
    content_research = Column(Text, nullable=True, comment="正文调研摘要")

    # 节点1：标题
    titles = Column(Text, nullable=True, comment="生成的3个标题，json字符串")
    title_scores = Column(Text, nullable=True, comment="标题评分，json字符串")
    selected_title = Column(String(512), nullable=True, comment="用户选择的标题")

    # 配图配置（人工介入点1：标题选择页只配置是否配图，配图方式在大纲确认页配置）
    need_image = Column(Boolean, default=False, comment="是否需要配图（标题选择页配置）")
    image_source = Column(String(32), nullable=True, comment="配图方式：api/ai（大纲确认页配置）")

    # 文章风格（人工介入点1：标题选择页配置，传给大纲调研和大纲师）
    article_style = Column(String(32), nullable=True, comment="文章风格：popular_science/technical/essay/prose/note/custom")
    article_style_custom = Column(String(256), nullable=True, comment="自定义风格时的用户输入")

    # 对大纲的额外要求（标题选择页填写，给大纲师）
    extra_requirements = Column(Text, nullable=True, comment="用户对大纲的额外要求（标题页填写，给大纲师）")

    # 正文写作配置（人工介入点2：大纲确认页填写，给写手）
    word_count = Column(Integer, nullable=True, comment="目标字数（大纲确认页填写，给写手）")
    level = Column(String(32), nullable=True, comment="专业水平（大纲确认页填写，给写手）")
    content_extra_requirements = Column(Text, nullable=True, comment="用户对正文的额外要求（大纲确认页填写，给写手）")

    # 节点2：大纲
    outline = Column(Text, nullable=True, comment="博客大纲")
    outline_confirmed = Column(Boolean, default=False, comment="大纲是否已确认")

    # 节点3：正文
    content = Column(Text, nullable=True, comment="博客正文markdown")
    writing_thoughts = Column(Text, nullable=True, comment="写手写作思路")

    # 审稿
    review_feedback = Column(Text, nullable=True, comment="审稿意见")

    # 配图
    image_urls = Column(Text, nullable=True, comment="配图URL列表，json字符串")

    # 格式化后
    formatted_content = Column(Text, nullable=True, comment="格式化后的正文")

    # 预留：配图提示词
    image_prompts = Column(Text, nullable=True, comment="配图提示词，json字符串")

    error = Column(Text, nullable=True, comment="错误信息")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
