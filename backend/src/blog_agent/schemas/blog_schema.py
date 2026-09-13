from pydantic import BaseModel, Field
from typing import Optional, List


class BlogDetailResp(BaseModel):
    """博客详情 — 任务完成后，返回完整博客内容"""
    task_id: int
    topic: str
    selected_title: Optional[str] = None  # 用户最终选择的标题
    outline: Optional[str] = None         # 大纲

    # 调研结果（右栏展示）
    title_research: Optional[str] = None      # 标题调研
    outline_research: Optional[str] = None    # 大纲调研
    content_research: Optional[str] = None    # 正文调研
    writing_thoughts: Optional[str] = None    # 写手写作思路

    # 大纲配置（左栏展示）
    target_word_count: Optional[int] = None   # 目标字数（大纲确认页填写，给写手）
    level: Optional[str] = None               # 专业水平（大纲确认页填写，给写手）
    extra_requirements: Optional[str] = None  # 对大纲的额外要求（标题页填写，给大纲师）
    content_extra_requirements: Optional[str] = None  # 对正文的额外要求（大纲确认页填写，给写手）
    article_style: Optional[str] = None       # 文章风格（标题页填写）
    article_style_custom: Optional[str] = None  # 自定义风格输入
    need_image: Optional[bool] = None         # 是否配图
    image_source: Optional[str] = None        # 配图方式

    content: Optional[str] = None         # 正文 markdown
    formatted_content: Optional[str] = None  # 格式化后的正文
    image_prompts: List[str] = []         # 配图提示词
    image_urls: List[str] = []            # 配图URL列表
    review_feedback: Optional[str] = None # 审稿记录
    word_count: Optional[int] = None      # 字数
    created_at: Optional[str] = None      # 创建时间


class BlogPublishReq(BaseModel):
    """发布博客 — 请求体（后续扩展，发布到公众号/知乎等）"""
    task_id: int
    platform: str = Field(description="发布平台：wechat/zhihu/juejin")
    title: Optional[str] = None


class BlogPublishResp(BaseModel):
    """发布结果 — 响应体"""
    task_id: int
    platform: str
    publish_url: Optional[str] = None
    status: str
