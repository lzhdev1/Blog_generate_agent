"""
幂等数据库迁移脚本：对已存在的表补齐缺失的列。
- 对 blog_task 等已存在表：ALTER TABLE ADD COLUMN IF NOT EXISTS 补齐 models 中定义但表里缺失的字段
- 新表由 init_db（create_all）负责创建
- 可安全重复执行（生产部署时每次 git pull 后自动运行）
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text
from src.blog_agent.db.session import SessionLocal, engine
from src.blog_agent.db import models


def type_to_sql(column):
    """把 SQLAlchemy Column 转成 PostgreSQL 的列定义片段（覆盖本项目用到的类型）"""
    t = column.type
    name = type(t).__name__
    if name == "Integer":
        return "INTEGER"
    if name == "String":
        return "VARCHAR(%d)" % (t.length or 255)
    if name == "Text":
        return "TEXT"
    if name == "Boolean":
        return "BOOLEAN"
    if name == "DateTime":
        return "TIMESTAMP"
    if name == "Numeric":
        return "NUMERIC(10, 2)"
    if name == "Enum":
        # 枚举类型保留原类型名（已由 init_db/create_all 创建）
        return "VARCHAR(32)"
    return "VARCHAR(255)"


def migrate():
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    changed = False

    for table_name, table in models.Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue  # 新表交给 init_db 创建
        existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
        missing = [c for c in table.columns if c.name not in existing_cols]
        if not missing:
            continue
        print(f"[migrate] 表 {table_name} 缺列: {[c.name for c in missing]}，开始补齐...")
        with engine.begin() as conn:
            for col in missing:
                sql_type = type_to_sql(col)
                nullable = "NULL" if col.nullable else "NOT NULL"
                default = ""
                if col.default is not None and col.default.is_scalar:
                    dv = col.default.arg
                    if isinstance(dv, bool):
                        default = f" DEFAULT {'TRUE' if dv else 'FALSE'}"
                    elif isinstance(dv, (int, float)):
                        default = f" DEFAULT {dv}"
                    elif isinstance(dv, str):
                        default = f" DEFAULT '{dv}'"
                ddl = f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{col.name}" {sql_type} {nullable}{default}'
                conn.execute(text(ddl))
                print(f"  + 已添加列: {col.name} ({sql_type})")
        changed = True

    if not changed:
        print("[migrate] 所有已存在的表结构均为最新，无需迁移。")
    else:
        print("[migrate] 迁移完成。")


if __name__ == "__main__":
    migrate()
