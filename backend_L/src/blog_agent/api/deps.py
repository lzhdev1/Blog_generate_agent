"""API 公共依赖：数据库会话 + 用户鉴权（get_current_user / get_optional_user）"""
from typing import Generator, Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.blog_agent.db.models import User
from src.blog_agent.db.session import SessionLocal, get_db
from src.blog_agent.service.auth_service import decode_access_token, get_user_by_id

# Bearer Token 提取器（auto_error=False：无 token 时手动返回 401，便于区分）
security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """依赖注入：解析 Bearer Token → 校验 → 返回当前用户（未登录/无效则 401）"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录，请先登录")
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被注销")
    return user


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """可选登录：有有效 token 返回用户，无 token 返回 None（公开接口用，不抛 401）"""
    if credentials is None:
        return None
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        return None
    user = get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        return None
    return user


__all__ = ["get_db", "SessionLocal", "get_current_user", "get_optional_user"]
