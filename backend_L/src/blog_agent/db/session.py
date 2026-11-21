"""数据库连接（PostgreSQL，与旧版一致的生产级配置）"""
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config.settings import settings

# PostgreSQL 连接池配置
engine = create_engine(
    settings.db_url,
    pool_size=10,           # 连接池大小
    pool_timeout=8,
    connect_args={"connect_timeout": 5} if settings.db_url.startswith("postgresql") else {},
    max_overflow=20,        # 超出 pool_size 后最多创建的连接数
    pool_pre_ping=True,     # 每次取出连接前先检测连接是否有效
    pool_recycle=3600,      # 连接回收时间（秒），避免 PostgreSQL 主动断开空闲连接
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI 依赖：请求级数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """启动时建表（开发环境直接 create_all；生产可换 Alembic 迁移）"""
    # 延迟导入，避免循环依赖
    from src.blog_agent.db import access_models, job_models, models  # noqa: F401
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(select(func.pg_advisory_xact_lock(1145849671, 2)))
        upgrade_editorial_schema(conn)
        Base.metadata.create_all(bind=conn)


def upgrade_editorial_schema(conn):
    """Additive upgrade for databases created by earlier API versions; safe to repeat."""
    inspector = inspect(conn)
    additions = {
        "blog_task": {"purpose": "VARCHAR(512)", "evidence_sources": "JSON",
                     "editorial_version": "INTEGER NOT NULL DEFAULT 0"},
        "generation_jobs": {"review_only": "BOOLEAN NOT NULL DEFAULT FALSE"},
        "editorial_drafts": {"source_query": "VARCHAR(300)", "evidence_sources": "JSON"},
    }
    for table, columns in additions.items():
        if inspector.has_table(table):
            present = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
