import json
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict
from datetime import datetime


class TaskCreateReq(BaseModel):
    """创建博客生成任务 — 请求体"""
    topic: str = Field(description="博客主题", min_length=1)


class TitleAndConfigReq(BaseModel):
    """用户选择标题 + 配图配置 — 请求体"""
    title: str = Field(description="用户选中的标题", min_length=1)
    need_image: bool = Field(description="是否需要配图", default=False)
    image_source: Optional[str] = Field(
        description="配图方式：api（图片网站搜索）/ ai（AI生成），need_image为true时必填",
        default=None
    )


class ConfirmOutlineReq(BaseModel):
    """用户确认大纲 — 请求体"""
    outline: Optional[str] = Field(
        default=None,
        description="修改后的大纲，不传则使用原大纲"
    )


class TaskResp(BaseModel):
    """任务状态查询 — 响应体"""
    id: int
    topic: str
    status: str
    progress: Optional[str] = None

    # 调研结果
    title_research: Optional[str] = None
    outline_research: Optional[str] = None

    # 标题
    titles: List[str] = []
    title_scores: List[Dict] = []
    selected_title: Optional[str] = None

    # 配图配置
    need_image: bool = False
    image_source: Optional[str] = None

    # 大纲
    outline: Optional[str] = None
    outline_confirmed: bool = False

    # 正文
    content: Optional[str] = None

    # 审稿
    review_feedback: Optional[str] = None

    # 配图
    image_urls: List[str] = []

    # 格式化
    formatted_content: Optional[str] = None

    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("titles", "image_urls", "title_scores", mode="before")
    @classmethod
    def parse_json_list(cls, v):
        """把数据库里的 None 或 JSON 字符串转成列表"""
        if v is None:
            return []
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
        return v

    class Config:
        from_attributes = True


class TaskListResp(BaseModel):
    """任务列表 — 响应体"""
    total: int
    items: List[TaskResp]
