"""任务/博客相关请求与响应模型（从旧版移植，新增审稿结果结构化字段）"""
import json
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime


class TaskCreateReq(BaseModel):
    """创建博客生成任务 — 请求体"""
    model_config = ConfigDict(str_strip_whitespace=True)
    topic: str = Field(description="博客主题", min_length=1, max_length=512)
    purpose: str | None = Field(None, max_length=512)
    level: Literal["general", "medium", "advanced", "professional"] | None = None
    word_count: int | None = Field(None, ge=100, le=10000)
    article_style: Literal["popular_science", "technical", "essay", "prose", "note", "custom"] | None = None
    article_style_custom: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def validate_custom_style(self):
        if self.article_style == "custom" and not self.article_style_custom:
            raise ValueError("请填写自定义风格")
        return self


class TitleAndConfigReq(BaseModel):
    """用户选择标题 + 是否配图 + 文章风格 + 对大纲的额外要求 — 请求体"""
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(description="用户选中的标题", min_length=1, max_length=512)
    purpose: str | None = Field(None, max_length=512)
    need_image: bool = Field(description="是否需要配图", default=False)
    article_style: Optional[str] = Field(
        description="文章风格：popular_science（科普）/ technical（技术）/ essay（论文）/ prose（散文）/ note（笔记）/ custom（自定义）",
        default=None, max_length=32
    )
    article_style_custom: Optional[str] = Field(
        description="自定义风格时的用户输入（article_style=custom时必填）",
        default=None,
        max_length=200
    )
    extra_requirements: Optional[str] = Field(
        description="用户对大纲的额外要求（指导大纲师生成大纲）",
        default=None,
        max_length=1000
    )


class ConfirmOutlineReq(BaseModel):
    """用户确认大纲 + 正文写作配置 + 配图方式 — 请求体"""
    outline: Optional[str] = Field(
        default=None,
        max_length=32000, description="修改后的大纲，不传则使用原大纲"
    )
    word_count: Optional[int] = Field(
        description="目标字数：300/500/800/自定义数字",
        default=None,
        ge=100,
        le=10000
    )
    level: Optional[str] = Field(
        description="专业水平：general（一般）/ medium（中等）/ advanced（高级）/ professional（专业）",
        default=None, max_length=32
    )
    content_extra_requirements: Optional[str] = Field(
        description="用户对正文的额外要求（指导写手生成正文）",
        default=None,
        max_length=1000
    )
    image_source: Optional[str] = Field(
        description="配图方式：api（图片网站搜索）/ ai（AI生成），need_image为true时必填",
        default=None
    )


class JobInfo(BaseModel):
    stage: str
    status: str
    attempt: int
    max_attempts: int


class TaskResp(BaseModel):
    """任务状态查询 — 响应体"""
    id: int
    topic: str
    purpose: str | None = None
    revision: str
    status: str
    progress: Optional[str] = None
    job: Optional[JobInfo] = None
    can_restore_previous: bool = False
    accepted_request_key: Optional[str] = None

    # 作者与可见性
    user_id: Optional[int] = None
    is_demo: bool = False
    is_public: bool = False
    allow_download: bool = False
    download_price: float = 0

    # 调研结果
    title_research: Optional[str] = None
    outline_research: Optional[str] = None
    content_research: Optional[str] = None
    evidence_sources: List[Dict[str, str]] = Field(default_factory=list)

    # 标题
    titles: List[str] = []
    title_scores: List[Dict] = []
    selected_title: Optional[str] = None

    # 配图配置
    need_image: bool = False
    image_source: Optional[str] = None

    # 文章风格
    article_style: Optional[str] = None
    article_style_custom: Optional[str] = None

    # 文章个性化配置
    word_count: Optional[int] = None
    level: Optional[str] = None
    extra_requirements: Optional[str] = None       # 对大纲的额外要求（标题页填写）
    content_extra_requirements: Optional[str] = None  # 对正文的额外要求（大纲页填写）

    # 大纲
    outline: Optional[str] = None
    outline_confirmed: bool = False

    # 正文
    content: Optional[str] = None
    writing_thoughts: Optional[str] = None

    # 审稿
    review_feedback: Optional[str] = None
    review_result: Optional[Dict[str, Any]] = Field(
        default=None, validation_alias=AliasChoices("review_result", "review_feedback")
    )

    # 配图
    image_urls: List[str] = []
    image_prompts: List[str] = []

    # 格式化
    formatted_content: Optional[str] = None

    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("titles", "image_urls", "title_scores", "image_prompts", "evidence_sources", mode="before")
    @classmethod
    def parse_json_list(cls, v):
        """把数据库里的 None 或 JSON 字符串转成列表"""
        if v is None:
            return []
        if isinstance(v, str):
            try:
                result = json.loads(v)
                return result if isinstance(result, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        return v

    @field_validator("review_result", mode="before")
    @classmethod
    def parse_review_result(cls, v):
        """把数据库里的 None 或 JSON 字符串转成对象"""
        if v is None:
            return None
        if isinstance(v, str):
            if not v.strip():
                return None
            if not v.lstrip().startswith("{"):
                return {"opinions_text": v}
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    class Config:
        from_attributes = True


class VisibilityReq(BaseModel):
    """文章可见性配置 —— 请求体"""
    is_public: bool = Field(description="是否公开", default=False)
    expected_revision: str = Field(min_length=64, max_length=64)
    allow_download: bool = Field(description="是否允许下载", default=False)
    download_price: float = Field(description="下载价格（元，0=免费）", default=0, ge=0, le=100000, multiple_of=0.01)


class DraftVersionReq(BaseModel):
    expected_version: int = Field(ge=0)


class DraftApplyReq(DraftVersionReq):
    expected_revision: str = Field(min_length=64, max_length=64)


class DraftSaveReq(DraftApplyReq):
    content: str = Field(min_length=1, max_length=64000)
    source_query: str | None = Field(None, max_length=300)


class EditorialDraftResp(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    base_revision: str
    version: int
    content: str
    source_query: str | None = None
    evidence_sources: list[dict] = Field(default_factory=list)
    status: str
    review_result: dict | None = None
    error: str | None = None

    @field_validator("evidence_sources", mode="before")
    @classmethod
    def source_list(cls, value):
        return value or []


class ArticleCardResp(BaseModel):
    """公开文章卡片 —— 响应体（全部文章页/首页随机展示用）"""
    task_id: int
    title: str
    topic: str
    nickname: Optional[str] = None        # 作者昵称
    is_demo: bool = False                 # 演示数据标记
    allow_download: bool = False
    download_price: float = 0
    like_count: int = 0
    created_at: Optional[datetime] = None
    status: str = ""


class TaskListResp(BaseModel):
    """任务列表 — 响应体"""
    total: int
    items: List[TaskResp]
