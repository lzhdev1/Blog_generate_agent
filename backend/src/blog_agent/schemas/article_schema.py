from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ArticleCardResp(BaseModel):
    """公开文章卡片 —— 响应体（全部文章页/首页随机展示）"""
    task_id: int
    title: str
    topic: str
    nickname: Optional[str] = None        # 作者昵称（demo 数据为"演示"）
    is_demo: bool = False
    allow_download: bool = False
    download_price: float = 0
    like_count: int = 0
    favorite_count: int = 0
    created_at: Optional[datetime] = None
    status: str = ""


class ArticleListResp(BaseModel):
    """公开文章列表 —— 响应体"""
    total: int
    items: List[ArticleCardResp]


class ArticleDetailResp(BaseModel):
    """公开文章详情 —— 响应体"""
    task_id: int
    title: str
    topic: str
    content: str
    nickname: Optional[str] = None
    is_demo: bool = False
    allow_download: bool = False
    download_price: float = 0
    like_count: int = 0
    liked: bool = False
    favorited: bool = False
    purchased: bool = False
    is_owner: bool = False
    created_at: Optional[datetime] = None


class MyArticleItemResp(BaseModel):
    """我的文章条目 —— 响应体（created/liked/favorited/purchased/downloaded）"""
    task_id: int
    title: str
    topic: str
    status: str = ""
    is_public: bool = False
    allow_download: bool = False
    download_price: float = 0
    like_count: int = 0
    purchased_price: Optional[float] = None   # 购买/下载时的价格（purchased/downloaded 分类）
    created_at: Optional[datetime] = None


class MyArticleListResp(BaseModel):
    total: int
    items: List[MyArticleItemResp]


class PurchaseResp(BaseModel):
    message: str
    balance: float = 0          # 购买后的剩余余额
    task_id: int


class DownloadResp(BaseModel):
    title: str
    content: str
    message: str = ""
