"""认证业务：注册、登录、改密、注销、验证码、模拟充值（从旧版移植）"""
import datetime
import random
import string

import bcrypt
import jwt
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.settings import settings
from src.blog_agent.db.models import Favorite, Like, Purchase, User
from src.blog_agent.db.access_models import SessionVersion
from src.blog_agent.service.email_verification import consume_code
from src.blog_agent.service.media_access import preserve_snapshot_media


# ========== 密码哈希 ==========

def hash_password(password: str) -> str:
    """bcrypt 哈希（cost=12，自动带盐）"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# ========== JWT ==========

def create_access_token(user_id: int, version: int = 0) -> str:
    """签发 JWT"""
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=settings.jwt_expire_minutes
    )
    payload = {"sub": str(user_id), "ver": version, "iss": f"blog-agent/{settings.app_env}", "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def user_from_token(db, token: str) -> User | None:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm],
                            options={"require": ["sub", "exp"]})
        issuer = claims.get("iss")
        if issuer != f"blog-agent/{settings.app_env}" and (issuer is not None or settings.app_env == "production"):
            return None
        user_id = int(claims["sub"])
        version = int(claims.get("ver", 0))  # Sessions issued before versioning used version zero.
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        return None
    result = (db.query(User, SessionVersion.version)
              .outerjoin(SessionVersion, SessionVersion.user_id == User.id)
              .filter(User.id == user_id).first())
    if not result or (result[1] or 0) != version:
        return None
    return result[0]


def token_for_user(db, user):
    row = db.get(SessionVersion, user.id)
    return create_access_token(user.id, row.version if row else 0)


# ========== 昵称生成 ==========

def generate_default_nickname() -> str:
    """默认昵称：Blog_ + 随机5位数字"""
    return "Blog_" + "".join(random.choices(string.digits, k=5))


# ========== 注册 / 登录 ==========

def register_user(db: Session, nickname: str, email: str, email_code: str,
                  username: str, password: str, confirm_password: str) -> User:
    """注册：校验验证码/用户名唯一/邮箱唯一/密码一致性，创建用户"""
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")

    email = email.strip().lower()
    consume_code(db, email, email_code)

    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="用户名已被注册")
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=400, detail="邮箱已被注册")

    user = User(
        username=username,
        email=email,
        nickname=nickname,
        password_hash=hash_password(password),
        email_verified=settings.effective_registration == "smtp",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail="该用户名或邮箱已被注册")
    db.refresh(user)
    return user


def authenticate_user(db: Session, account: str, password: str) -> User:
    """登录：用户名或邮箱 + 密码"""
    if "@" in account:
        user = db.query(User).filter(func.lower(User.email) == account.strip().lower()).with_for_update().first()
    else:
        user = db.query(User).filter(User.username == account).with_for_update().first()
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被注销")
    return user


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


# ========== 修改密码 / 注销 ==========

def change_password(db: Session, user: User, old_password: str,
                    new_password: str, confirm_new_password: str) -> None:
    db.refresh(user, with_for_update=True)
    if not verify_password(old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")
    if new_password != confirm_new_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")
    if old_password == new_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")
    user.password_hash = hash_password(new_password)
    row = db.get(SessionVersion, user.id)
    if row:
        row.version += 1
    else:
        db.add(SessionVersion(user_id=user.id, version=1))
    db.commit()


def deactivate_account(db: Session, user: User) -> None:
    """注销账号（硬删除）：删除用户及其创建的文章。

    付费/下载用户不受影响：其他用户对该作者文章的 Purchase/DownloadRecord
    快照（title/content_snapshot）保留，仅解除 task_id 引用。
    """
    from src.blog_agent.db.models import BlogTask, DownloadRecord, Notification
    user_id = user.id

    # 该作者创建的文章 ID
    task_ids = [t.id for t in db.query(BlogTask.id).filter_by(user_id=user_id).order_by(BlogTask.id).with_for_update()]
    from src.blog_agent.service.job_queue import active_jobs
    if active_jobs(db, user_id):
        raise HTTPException(409, detail="还有已提交的生成任务，请在任务结束后注销账号。")
    preserve_snapshot_media(db, task_ids)

    # 1) 其他用户对这些文章的点赞/收藏：直接删除（非快照数据）
    if task_ids:
        db.query(Favorite).filter(Favorite.task_id.in_(task_ids)).delete(synchronize_session=False)
        db.query(Like).filter(Like.task_id.in_(task_ids)).delete(synchronize_session=False)
        # 2) 付费/下载快照保留：解除 task 引用（内容在 content_snapshot，作者注销不影响）
        db.query(Purchase).filter(Purchase.task_id.in_(task_ids)).update(
            {Purchase.task_id: None}, synchronize_session=False)
        db.query(DownloadRecord).filter(DownloadRecord.task_id.in_(task_ids)).update(
            {DownloadRecord.task_id: None}, synchronize_session=False)
        # 3) 关联这些文章的站内通知：删除（通知无内容快照，作者注销即清）
        db.query(Notification).filter(Notification.task_id.in_(task_ids)).delete(synchronize_session=False)

    # 4) 删除该用户自己产生的关联数据
    db.query(Favorite).filter(Favorite.user_id == user_id).delete(synchronize_session=False)
    db.query(Like).filter(Like.user_id == user_id).delete(synchronize_session=False)
    db.query(Purchase).filter(Purchase.user_id == user_id).delete(synchronize_session=False)
    db.query(DownloadRecord).filter(DownloadRecord.user_id == user_id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id == user_id).delete(synchronize_session=False)

    # 5) 删除该用户创建的文章 + 用户本身
    db.query(BlogTask).filter(BlogTask.user_id == user_id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()


# ========== 模拟充值 ==========

def recharge_balance(db: Session, user: User, amount: float) -> User:
    """模拟充值：直接加余额（开发期用；后续接入真实支付网关后由支付回调调用）"""
    user.balance = float(user.balance or 0) + amount
    db.commit()
    db.refresh(user)
    return user
