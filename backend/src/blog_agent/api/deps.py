from typing import Generator

from sqlalchemy.orm import Session

from src.blog_agent.db.session import SessionLocal


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
