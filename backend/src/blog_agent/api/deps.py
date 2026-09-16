from typing import Generator

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.blog_agent.db.models import User
from src.blog_agent.db.session import SessionLocal
from src.blog_agent.service.auth_service import decode_access_token, get_user_by_id

# Bearer Token 提取器（auto_error=False：无 token 时手动返回 401，便于区分）
security = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """
    依赖注入：每个请求创建一个数据库会话，请求结束自动关闭
    接口函数参数里写 db: Session = Depends(get_db) 就能拿到会话
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
