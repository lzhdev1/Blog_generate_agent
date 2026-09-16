"""认证业务：注册、登录、改密、注销、验证码、模拟充值"""
import datetime
import random
import string

import bcrypt
import jwt
from fastapi import HTTPException
from sqlalchemy.orm import Session

from config.settings import settings
from src.blog_agent.db.models import User


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

def create_access_token(user_id: int) -> str:
    """签发 JWT"""
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=settings.jwt_expire_minutes
    )
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int | None:
    """解析 JWT，返回 user_id；无效返回 None"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return int(payload.get("sub", 0))
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        return None


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

    # 开发阶段验证码固定 888888；接入真实 SMTP 后改为校验发送记录
    if email_code != settings.email_code_default:
        raise HTTPException(status_code=400, detail="邮箱验证码错误")

    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="用户名已被注册")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="邮箱已被注册")

    user = User(
        username=username,
        email=email,
        nickname=nickname,
        password_hash=hash_password(password),
        email_verified=True,  # 验证码通过即视为已验证
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, account: str, password: str) -> User:
    """登录：用户名或邮箱 + 密码"""
    if "@" in account:
        user = db.query(User).filter(User.email == account).first()
    else:
        user = db.query(User).filter(User.username == account).first()
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
    if not verify_password(old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")
    if new_password != confirm_new_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")
    if old_password == new_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")
    user.password_hash = hash_password(new_password)
    db.commit()


def deactivate_account(db: Session, user: User) -> None:
    """注销账号（硬删除）：删除用户及其创建的文章"""
    from src.blog_agent.db.models import BlogTask, Favorite, Like, Purchase
    user_id = user.id
    # 删除关联数据
    db.query(Favorite).filter(Favorite.user_id == user_id).delete()
    db.query(Like).filter(Like.user_id == user_id).delete()
    db.query(Purchase).filter(Purchase.user_id == user_id).delete()
    # 删除该用户创建的文章（付费用户已有内容快照，不受影响）
    db.query(BlogTask).filter(BlogTask.user_id == user_id).delete()
    db.delete(user)
    db.commit()


# ========== 模拟充值 ==========

def recharge_balance(db: Session, user: User, amount: float) -> User:
    """模拟充值：直接加余额（开发期用；后续接入真实支付网关后由支付回调调用）"""
    user.balance = float(user.balance or 0) + amount
    db.commit()
    db.refresh(user)
    return user
