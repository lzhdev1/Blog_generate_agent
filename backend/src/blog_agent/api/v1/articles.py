from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from src.blog_agent.api.deps import get_db, get_current_user, get_optional_user
from src.blog_agent.db.models import BlogTask, User, Favorite, Like, Purchase, DownloadRecord, TaskStatus
from src.blog_agent.schemas.article_schema import (
    ArticleCardResp,
    ArticleListResp,
    ArticleDetailResp,
    MyArticleItemResp,
    MyArticleListResp,
    PurchaseResp,
    DownloadResp,
)
from src.blog_agent.service.task_service import TaskService

router = APIRouter(prefix="/api/v1", tags=["文章广场"])

# 已产出正文的状态
_DONE_STATUSES = ("content_generated", "completed")


def _get_public_task(db: Session, task_id: int) -> BlogTask:
    """查询公开文章：is_demo 或 is_public 且已生成正文；否则 404"""
    task = TaskService.get_task(db, task_id=task_id)
    if not task or task.status not in _DONE_STATUSES:
        raise HTTPException(status_code=404, detail="文章不存在")
    if not (task.is_demo or task.is_public):
        raise HTTPException(status_code=404, detail="文章不存在")
    return task


def _like_count(db: Session, task_id: int) -> int:
    return db.query(Like).filter(Like.task_id == task_id).count()


def _favorite_count(db: Session, task_id: int) -> int:
    return db.query(Favorite).filter(Favorite.task_id == task_id).count()


def _nickname(db: Session, user_id: Optional[int]) -> str:
    if user_id is None:
        return "演示"
    u = db.query(User).filter(User.id == user_id).first()
    return u.nickname if u else "未知作者"


def _card(db: Session, task: BlogTask) -> ArticleCardResp:
    return ArticleCardResp(
        task_id=task.id,
        title=task.selected_title or task.topic,
        topic=task.topic,
        nickname=_nickname(db, task.user_id),
        is_demo=task.is_demo,
        allow_download=task.allow_download,
        download_price=float(task.download_price or 0),
        like_count=_like_count(db, task.id),
        favorite_count=_favorite_count(db, task.id),
        created_at=task.created_at,
        status=task.status,
    )


# ========== 全部文章（公开文章流） ==========

@router.get("/articles", response_model=ArticleListResp, summary="全部文章（公开+演示），支持随机")
def list_articles(
    limit: int = 8,
    offset: int = 0,
    random: bool = True,
    db: Session = Depends(get_db),
):
    """公开文章列表：演示数据 + 用户公开的文章。random=true 随机排序（首页/换一批用）"""
    query = (
        db.query(BlogTask)
        .filter(or_(BlogTask.is_demo.is_(True), BlogTask.is_public.is_(True)))
        .filter(BlogTask.status.in_(_DONE_STATUSES))
    )
    total = query.count()
    q = query
    if random:
        q = q.order_by(func.random())
    else:
        q = q.order_by(BlogTask.created_at.desc())
    items = q.offset(offset).limit(limit).all()
    return {"total": total, "items": [_card(db, t) for t in items]}


# ========== 文章详情 ==========

@router.get("/articles/{task_id}", response_model=ArticleDetailResp, summary="公开文章详情")
def get_article(task_id: int, db: Session = Depends(get_db),
                current_user: Optional[User] = Depends(get_optional_user)):
    """查看公开文章。登录后可看到自己的点赞/收藏/购买状态；作者本人可看到 is_owner"""
    task = _get_public_task(db, task_id)
    uid = current_user.id if current_user else None
    content = task.formatted_content or task.content or ""

    liked = favorited = purchased = False
    if uid:
        liked = db.query(Like).filter(Like.user_id == uid, Like.task_id == task_id).first() is not None
        favorited = db.query(Favorite).filter(Favorite.user_id == uid, Favorite.task_id == task_id).first() is not None
        purchased = db.query(Purchase).filter(Purchase.user_id == uid, Purchase.task_id == task_id).first() is not None

    return ArticleDetailResp(
        task_id=task.id,
        title=task.selected_title or task.topic,
        topic=task.topic,
        content=content,
        nickname=_nickname(db, task.user_id),
        is_demo=task.is_demo,
        allow_download=task.allow_download,
        download_price=float(task.download_price or 0),
        like_count=_like_count(db, task.id),
        liked=liked,
        favorited=favorited,
        purchased=purchased,
        is_owner=(uid is not None and task.user_id == uid),
        created_at=task.created_at,
    )


# ========== 点赞 / 收藏 ==========

@router.post("/articles/{task_id}/like", summary="点赞/取消点赞")
def toggle_like(task_id: int, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    task = _get_public_task(db, task_id)
    row = db.query(Like).filter(Like.user_id == current_user.id, Like.task_id == task_id).first()
    if row:
        db.delete(row)
        db.commit()
        return {"liked": False, "like_count": _like_count(db, task_id)}
    db.add(Like(user_id=current_user.id, task_id=task_id))
    db.commit()
    return {"liked": True, "like_count": _like_count(db, task_id)}


@router.post("/articles/{task_id}/favorite", summary="收藏/取消收藏")
def toggle_favorite(task_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    _get_public_task(db, task_id)
    row = db.query(Favorite).filter(Favorite.user_id == current_user.id, Favorite.task_id == task_id).first()
    if row:
        db.delete(row)
        db.commit()
        return {"favorited": False}
    db.add(Favorite(user_id=current_user.id, task_id=task_id))
    db.commit()
    return {"favorited": True}


# ========== 付费购买（模拟支付闭环） ==========

@router.post("/articles/{task_id}/purchase", response_model=PurchaseResp, summary="付费购买文章（余额扣款）")
def purchase_article(task_id: int, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    task = _get_public_task(db, task_id)
    price = float(task.download_price or 0)

    # 已购买直接返回
    existing = db.query(Purchase).filter(Purchase.user_id == current_user.id, Purchase.task_id == task_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="您已购买过该文章")

    # 免费/演示文章无需购买
    if task.is_demo or price <= 0:
        raise HTTPException(status_code=400, detail="该文章免费，无需购买")

    if current_user.balance < price:
        raise HTTPException(status_code=400, detail=f"余额不足，需要 {price} 元，当前余额 {current_user.balance} 元")

    # 扣款 + 快照
    current_user.balance -= price
    content = task.formatted_content or task.content or ""
    db.add(Purchase(
        user_id=current_user.id,
        task_id=task_id,
        title=task.selected_title or task.topic,
        content_snapshot=content,
        price=price,
    ))
    # 作者收款
    if task.user_id:
        author = db.query(User).filter(User.id == task.user_id).first()
        if author:
            author.balance += price
    db.commit()
    db.refresh(current_user)
    return PurchaseResp(message="购买成功", balance=float(current_user.balance), task_id=task_id)


# ========== 下载 ==========

@router.post("/articles/{task_id}/download", response_model=DownloadResp, summary="下载文章（作者/已购/免费）")
def download_article(task_id: int, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    task = _get_public_task(db, task_id)
    uid = current_user.id
    content = task.formatted_content or task.content or ""

    # 作者本人直接下载
    if task.user_id == uid and not task.is_demo:
        return DownloadResp(title=task.selected_title or task.topic, content=content, message="作者本人下载")

    if not task.allow_download and not task.is_demo:
        raise HTTPException(status_code=403, detail="作者未开放下载")

    # 付费文章：必须已购买
    price = float(task.download_price or 0)
    if price > 0 and not task.is_demo:
        purchased = db.query(Purchase).filter(Purchase.user_id == uid, Purchase.task_id == task_id).first()
        if not purchased:
            raise HTTPException(status_code=400, detail=f"请先购买后再下载（{price} 元）")
        # 记录下载次数
        purchased.download_count = (purchased.download_count or 0) + 1
        purchased.last_download_at = func.now()

    # 写下载记录（快照）
    existing = db.query(DownloadRecord).filter(DownloadRecord.user_id == uid, DownloadRecord.task_id == task_id).first()
    if not existing:
        db.add(DownloadRecord(
            user_id=uid,
            task_id=task_id,
            title=task.selected_title or task.topic,
            content_snapshot=content,
        ))
    db.commit()
    return DownloadResp(title=task.selected_title or task.topic, content=content, message="下载成功")


# ========== 我的文章（5 个分类） ==========

@router.get("/my/articles", response_model=MyArticleListResp, summary="我的文章（created/liked/favorited/purchased/downloaded）")
def my_articles(tab: str = "created", db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    uid = current_user.id
    tab = tab or "created"

    if tab == "liked":
        rows = (
            db.query(BlogTask)
            .join(Like, Like.task_id == BlogTask.id)
            .filter(Like.user_id == uid)
            .order_by(Like.created_at.desc())
            .all()
        )
        return {"total": len(rows), "items": [_my_item(db, t) for t in rows]}

    if tab == "favorited":
        rows = (
            db.query(BlogTask)
            .join(Favorite, Favorite.task_id == BlogTask.id)
            .filter(Favorite.user_id == uid)
            .order_by(Favorite.created_at.desc())
            .all()
        )
        return {"total": len(rows), "items": [_my_item(db, t) for t in rows]}

    if tab == "purchased":
        rows = (
            db.query(Purchase)
            .filter(Purchase.user_id == uid)
            .order_by(Purchase.created_at.desc())
            .all()
        )
        items = []
        for p in rows:
            task = TaskService.get_task(db, p.task_id)
            items.append(MyArticleItemResp(
                task_id=p.task_id,
                title=p.title or (task.selected_title if task else "已下架文章"),
                topic=task.topic if task else "",
                status=task.status if task else "",
                is_public=task.is_public if task else False,
                allow_download=task.allow_download if task else False,
                download_price=float(task.download_price or 0) if task else float(p.price or 0),
                like_count=_like_count(db, p.task_id) if task else 0,
                purchased_price=float(p.price or 0),
                created_at=p.created_at,
            ))
        return {"total": len(items), "items": items}

    if tab == "downloaded":
        rows = (
            db.query(DownloadRecord)
            .filter(DownloadRecord.user_id == uid)
            .order_by(DownloadRecord.created_at.desc())
            .all()
        )
        items = []
        for d in rows:
            task = TaskService.get_task(db, d.task_id)
            items.append(MyArticleItemResp(
                task_id=d.task_id,
                title=d.title or (task.selected_title if task else "已下架文章"),
                topic=task.topic if task else "",
                status=task.status if task else "",
                is_public=task.is_public if task else False,
                allow_download=task.allow_download if task else False,
                download_price=float(task.download_price or 0) if task else 0,
                like_count=_like_count(db, d.task_id) if task else 0,
                created_at=d.created_at,
            ))
        return {"total": len(items), "items": items}

    # 默认 created：我创建的
    total, items = TaskService.list_tasks(db, limit=200, offset=0, user_id=uid)
    return {"total": total, "items": [_my_item(db, t) for t in items]}


def _my_item(db: Session, task: BlogTask) -> MyArticleItemResp:
    return MyArticleItemResp(
        task_id=task.id,
        title=task.selected_title or task.topic,
        topic=task.topic,
        status=task.status,
        is_public=task.is_public,
        allow_download=task.allow_download,
        download_price=float(task.download_price or 0),
        like_count=_like_count(db, task.id),
        created_at=task.created_at,
    )
