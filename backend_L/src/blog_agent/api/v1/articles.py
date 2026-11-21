"""文章广场 API：公开文章流 / 搜索 / 详情 / 点赞 / 收藏 / 付费购买 / 下载 / 我的文章（从旧版移植）"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.orm import Session

from src.blog_agent.api.deps import get_current_user, get_db, get_optional_user
from src.blog_agent.agent.evidence import cited_sources, export_with_sources
from src.blog_agent.api.v1.notifications import create_notification
from src.blog_agent.db.job_models import GenerationJob
from src.blog_agent.db.models import (
    BlogTask,
    DownloadRecord,
    Favorite,
    Like,
    Purchase,
    TaskStatus,
    User,
)
from src.blog_agent.schemas.article_schema import (
    ArticleDetailResp,
    ArticleListResp,
    DownloadResp,
    MyArticleListResp,
    PurchaseResp,
    PurchaseQuote,
    SnapshotResp,
)

router = APIRouter(prefix="/api/v1", tags=["文章广场"])

# 已产出正文的状态
_DONE_STATUSES = (TaskStatus.CONTENT_GENERATED, TaskStatus.COMPLETED)


def _get_readable_task(db: Session, task_id: int, owner_id: int | None = None, *, lock: bool = False) -> BlogTask:
    query = db.query(BlogTask).filter_by(id=task_id)
    if lock:
        query = query.with_for_update().populate_existing()
    task = query.first()
    if not task or task.status not in _DONE_STATUSES:
        raise HTTPException(status_code=404, detail="文章不存在")
    if not (task.is_demo or task.is_public or (owner_id is not None and task.user_id == owner_id)):
        raise HTTPException(status_code=404, detail="文章不存在")
    return task


def _like_count(db: Session, task_id: int) -> int:
    return db.query(Like).filter(Like.task_id == task_id).count()


def _nickname(db: Session, user_id: Optional[int]) -> str:
    if user_id is None:
        return "演示"
    u = db.query(User).filter(User.id == user_id).first()
    return u.nickname if u else "未知作者"


def _interaction_count(model):
    return select(func.count(model.id)).where(model.task_id == BlogTask.id).correlate(BlogTask).scalar_subquery()


def _public_cards(db: Session, viewer: Optional[User]):
    def selected(model):
        if viewer is None:
            return literal(False)
        return select(model.id).where(model.task_id == BlogTask.id, model.user_id == viewer.id).exists()

    return (
        db.query(
            BlogTask.id.label("task_id"), func.coalesce(BlogTask.selected_title, BlogTask.topic).label("title"),
            BlogTask.topic, BlogTask.article_style, BlogTask.is_demo, BlogTask.allow_download,
            BlogTask.download_price, BlogTask.created_at, BlogTask.status,
            case((BlogTask.user_id.is_(None), "演示"), else_=User.nickname).label("nickname"),
            _interaction_count(Like).label("like_count"), _interaction_count(Favorite).label("favorite_count"),
            selected(Like).label("liked"), selected(Favorite).label("favorited"),
        )
        .select_from(BlogTask).outerjoin(User, User.id == BlogTask.user_id)
        .filter(or_(BlogTask.is_demo.is_(True), BlogTask.is_public.is_(True)), BlogTask.status.in_(_DONE_STATUSES))
    )


def _page(query, order_by, offset: int, limit: int):
    total = query.with_entities(BlogTask.id).count()
    rows = query.order_by(*order_by).offset(offset).limit(limit)
    return {"total": total, "items": [row._mapping for row in rows]}


# ========== 全部文章（公开文章流） ==========

@router.get("/articles", response_model=ArticleListResp, summary="全部文章（公开+演示），支持随机")
def list_articles(
    limit: int = Query(8, ge=1, le=200),
    offset: int = Query(0, ge=0),
    random: bool = True,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """公开文章列表：演示数据 + 用户公开的文章。random=true 随机排序（首页/换一批用）"""
    order = (func.random(),) if random else (BlogTask.created_at.desc(), BlogTask.id.desc())
    return _page(_public_cards(db, current_user), order, offset, limit)


# ========== 搜索 ==========

@router.get("/articles/search", response_model=ArticleListResp, summary="搜索公开文章（标题/主题模糊匹配）")
def search_articles(
    q: str = Query("", max_length=256),
    limit: int = Query(8, ge=1, le=20),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """关键字模糊搜索公开文章：匹配最终标题或用户主题，实时输入建议用"""
    query = _public_cards(db, current_user)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                BlogTask.selected_title.ilike(like),
                BlogTask.topic.ilike(like),
            )
        )
    return _page(query, (BlogTask.created_at.desc(), BlogTask.id.desc()), offset, limit)


# ========== 文章详情 ==========

@router.get("/articles/{task_id}", response_model=ArticleDetailResp, summary="公开文章详情")
def get_article(task_id: int, db: Session = Depends(get_db),
                current_user: Optional[User] = Depends(get_optional_user)):
    """查看公开文章。登录后可看到自己的点赞/收藏/购买状态；作者本人可看到 is_owner"""
    uid = current_user.id if current_user else None
    task = _get_readable_task(db, task_id, uid)
    is_owner = (uid is not None and task.user_id == uid)
    content = task.formatted_content or task.content or ""

    liked = favorited = purchased = False
    if uid:
        liked = db.query(Like).filter(Like.user_id == uid, Like.task_id == task_id).first() is not None
        favorited = db.query(Favorite).filter(Favorite.user_id == uid, Favorite.task_id == task_id).first() is not None
        purchased = db.query(Purchase).filter(Purchase.user_id == uid, Purchase.task_id == task_id).first() is not None

    return ArticleDetailResp(
        task_id=task.id,
        revision=task.revision,
        title=task.selected_title or task.topic,
        article_style=task.article_style,
        topic=task.topic,
        content=content,
        evidence_sources=cited_sources(content, task.evidence_sources),
        nickname=_nickname(db, task.user_id),
        is_demo=task.is_demo,
        allow_download=task.allow_download,
        download_price=float(task.download_price or 0),
        like_count=_like_count(db, task.id),
        liked=liked,
        favorited=favorited,
        purchased=purchased,
        is_owner=is_owner,
        created_at=task.created_at,
    )


# ========== 点赞 / 收藏 ==========

@router.post("/articles/{task_id}/like", summary="点赞/取消点赞")
def toggle_like(task_id: int, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    task = _get_readable_task(db, task_id, lock=True)
    row = db.query(Like).filter(Like.user_id == current_user.id, Like.task_id == task_id).first()
    if row:
        db.delete(row)
        db.commit()
        return {"liked": False, "like_count": _like_count(db, task_id)}
    db.add(Like(user_id=current_user.id, task_id=task_id))
    # 通知作者（自己给自己点赞不通知）
    if task.user_id and task.user_id != current_user.id:
        create_notification(
            db,
            user_id=task.user_id,
            ntype="like",
            content=f"用户「{current_user.nickname}」点赞了你的文章《{task.selected_title or task.topic}》",
            task_id=task_id,
            actor_name=current_user.nickname,
        )
    db.commit()
    return {"liked": True, "like_count": _like_count(db, task_id)}


@router.post("/articles/{task_id}/favorite", summary="收藏/取消收藏")
def toggle_favorite(task_id: int, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    task = _get_readable_task(db, task_id, lock=True)
    row = db.query(Favorite).filter(Favorite.user_id == current_user.id, Favorite.task_id == task_id).first()
    if row:
        db.delete(row)
        db.commit()
        return {"favorited": False}
    db.add(Favorite(user_id=current_user.id, task_id=task_id))
    # 通知作者（自己收藏自己的文章不通知）
    if task.user_id and task.user_id != current_user.id:
        create_notification(
            db,
            user_id=task.user_id,
            ntype="favorite",
            content=f"用户「{current_user.nickname}」收藏了你的文章《{task.selected_title or task.topic}》",
            task_id=task_id,
            actor_name=current_user.nickname,
        )
    db.commit()
    return {"favorited": True}


# ========== 付费购买（模拟支付闭环） ==========

@router.post("/articles/{task_id}/purchase", response_model=PurchaseResp, summary="付费购买文章（余额扣款）")
def purchase_article(task_id: int, req: PurchaseQuote, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    task = _get_readable_task(db, task_id, lock=True)
    price = task.download_price or 0

    # 已购买直接返回
    existing = db.query(Purchase).filter(Purchase.user_id == current_user.id, Purchase.task_id == task_id).first()
    if existing:
        db.refresh(current_user)
        return PurchaseResp(message="您已购买过该文章", balance=float(current_user.balance), task_id=task_id)

    if req.expected_revision != task.revision or req.expected_price != price:
        raise HTTPException(409, "文章版本或报价已更新，请重新查看后确认购买")

    # 免费/演示文章无需购买
    if task.is_demo or price <= 0:
        raise HTTPException(status_code=400, detail="该文章免费，无需购买")
    if task.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="作者可直接下载自己的文章")
    if not task.allow_download:
        raise HTTPException(status_code=403, detail="作者未开放下载")

    # 两个账户按相同顺序加锁，购买不同文章时也能正确结算余额。
    accounts = {
        user.id: user for user in db.query(User)
        .filter(User.id.in_([current_user.id, task.user_id]))
        .order_by(User.id).with_for_update().populate_existing()
    }
    if (current_user.balance or 0) < price:
        raise HTTPException(status_code=400, detail=f"余额不足，需要 {price} 元，当前余额 {float(current_user.balance or 0)} 元")

    current_user.balance -= price
    content = export_with_sources(task.formatted_content or task.content or "", task.evidence_sources)
    db.add(Purchase(
        user_id=current_user.id,
        task_id=task_id,
        title=task.selected_title or task.topic,
        content_snapshot=content,
        price=price,
    ))
    # 作者收款
    author = accounts.get(task.user_id)
    if author:
        author.balance = (author.balance or 0) + price
        create_notification(
            db, user_id=author.id, ntype="purchase",
            content=f"用户「{current_user.nickname}」付费 {price} 元购买了你的文章《{task.selected_title or task.topic}》",
            task_id=task_id, actor_name=current_user.nickname,
        )
    db.commit()
    db.refresh(current_user)
    return PurchaseResp(message="购买成功", balance=float(current_user.balance), task_id=task_id)


# ========== 下载 ==========

@router.post("/articles/{task_id}/download", response_model=DownloadResp, summary="下载文章（作者/已购/免费）")
def download_article(task_id: int, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    uid = current_user.id
    task = _get_readable_task(db, task_id, uid, lock=True)
    content = export_with_sources(task.formatted_content or task.content or "", task.evidence_sources)

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
def my_articles(tab: Literal["created", "liked", "favorited", "purchased", "downloaded"] = "created",
                limit: int | None = Query(None, ge=1, le=200), offset: int = Query(0, ge=0),
                db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    uid = current_user.id
    readable = or_(BlogTask.is_public.is_(True), BlogTask.is_demo.is_(True), BlogTask.user_id == uid)
    summary = (
        BlogTask.topic, BlogTask.article_style, BlogTask.status,
        BlogTask.is_public, BlogTask.allow_download, BlogTask.download_price,
        _interaction_count(Like).label("like_count"),
    )
    if tab in ("purchased", "downloaded"):
        model = Purchase if tab == "purchased" else DownloadRecord
        price = model.price if tab == "purchased" else literal(None)
        # 历史快照独立于原文；已转私密或正在重写的作品不展示当前创作信息。
        query = (
            db.query(
                model.id.label("record_id"), func.coalesce(model.task_id, 0).label("task_id"),
                func.coalesce(model.title, BlogTask.selected_title, "历史文章").label("title"),
                model.created_at, price.label("purchased_price"),
                func.coalesce(BlogTask.topic, "").label("topic"), BlogTask.article_style,
                func.coalesce(BlogTask.is_public, False).label("is_public"),
                func.coalesce(BlogTask.allow_download, False).label("allow_download"),
                func.coalesce(BlogTask.download_price, price, 0).label("download_price"),
                BlogTask.status, _interaction_count(Like).label("like_count"),
            )
            .select_from(model)
            .outerjoin(BlogTask, (BlogTask.id == model.task_id) & readable & BlogTask.status.in_(_DONE_STATUSES))
            .filter(model.user_id == uid)
        )
    else:
        query = db.query(
            BlogTask.id.label("task_id"), func.coalesce(BlogTask.selected_title, BlogTask.topic).label("title"),
            BlogTask.created_at, *summary,
        ).select_from(BlogTask)
        if tab == "created":
            model = BlogTask
            last_status = select(GenerationJob.status).where(GenerationJob.task_id == BlogTask.id, GenerationJob.review_only.is_(False)).order_by(
                GenerationJob.id.desc()).limit(1).scalar_subquery()
            query = query.add_columns(
                BlogTask.selected_title, BlogTask.outline_confirmed, last_status.label("job_status"),
            ).filter(BlogTask.user_id == uid)
            limit = limit or 200
        else:
            model = Like if tab == "liked" else Favorite
            query = query.join(model, model.task_id == BlogTask.id).filter(
                model.user_id == uid, readable, BlogTask.status.in_(_DONE_STATUSES)
            )

    total = query.with_entities(model.id).count()
    rows = query.order_by(model.created_at.desc(), model.id.desc()).offset(offset).limit(limit)
    items = [dict(row._mapping, status=row.status or "") for row in rows]
    return {"total": total, "items": items}


@router.get("/my/articles/{kind}/{record_id}", response_model=SnapshotResp, summary="读取购买或下载时保存的文章")
def get_snapshot(kind: Literal["purchased", "downloaded"], record_id: int,
                 db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    model = Purchase if kind == "purchased" else DownloadRecord
    record = db.query(model).filter_by(id=record_id, user_id=current_user.id).first()
    if not record:
        raise HTTPException(status_code=404, detail="文章快照不存在")
    return SnapshotResp(
        title=record.title or "历史文章",
        content=record.content_snapshot or "",
        created_at=record.created_at,
    )
