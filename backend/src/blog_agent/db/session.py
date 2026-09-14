from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config.settings import settings

# PostgreSQL 连接池配置
engine = create_engine(
    settings.db_url,
    pool_size=10,           # 连接池大小
    max_overflow=20,        # 超出 pool_size 后最多创建的连接数
    pool_pre_ping=True,     # 每次取出连接前先检测连接是否有效
    pool_recycle=3600,      # 连接回收时间（秒），避免 PostgreSQL 主动断开空闲连接
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
