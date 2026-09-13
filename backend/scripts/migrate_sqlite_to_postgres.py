"""
从 SQLite 迁移数据到 PostgreSQL

用法（在 backend 容器或已安装依赖的环境执行）：
    python scripts/migrate_sqlite_to_postgres.py [sqlite_db_path]

前置条件：
1. postgres 容器已启动且健康
2. postgres 中表已创建（先执行 python scripts/init_db.py）
3. 环境变量 db_url 指向 postgresql（docker compose 已配置）
"""
import sys

from sqlalchemy import create_engine, text


def main():
    # sqlite 文件路径：默认 docker 卷挂载路径，可用参数覆盖
    sqlite_path = sys.argv[1] if len(sys.argv) > 1 else "/app/data/blog_agent.db"

    from config.settings import settings
    pg_url = settings.db_url
    if not pg_url.startswith("postgresql"):
        print(f"错误：db_url 不是 postgresql 连接（当前: {pg_url}）")
        return

    sqlite_engine = create_engine(f"sqlite:///{sqlite_path}")
    pg_engine = create_engine(pg_url)

    # 1. 读取 sqlite 全部表（排除 sqlite 内部表）
    with sqlite_engine.connect() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            )
        ]
    print("sqlite 中的表:", tables)

    for table in tables:
        with sqlite_engine.connect() as conn:
            rows = conn.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings().all()
        if not rows:
            print(f"[{table}] 无数据，跳过")
            continue

        # 2. 防重复迁移：postgres 已有数据则跳过
        with pg_engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        if count > 0:
            print(f"[{table}] postgres 已有 {count} 条记录，跳过（如需重迁请先清空 postgres 该表）")
            continue

        # 3. 识别 postgres 的 boolean 列（sqlite 存 1/0，需转成 True/False）
        with pg_engine.connect() as conn:
            bool_cols = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = :t AND data_type = 'boolean'"
                    ),
                    {"t": table},
                )
            }
        if bool_cols:
            print(f"[{table}] boolean 列: {sorted(bool_cols)}")

        # 4. 逐行插入（显式带 id，保持原主键）
        cols = list(rows[0].keys())
        col_str = ", ".join(cols)
        placeholders = ", ".join([f":{c}" for c in cols])

        with pg_engine.begin() as conn:
            for row in rows:
                data = dict(row)
                for c in bool_cols:
                    if c in data and data[c] is not None:
                        data[c] = bool(data[c])
                conn.execute(
                    text(f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})"),
                    data,
                )
        print(f"[{table}] 迁移完成：{len(rows)} 条记录")

        # 5. 重置自增序列：显式插入 id 后，序列需从 max(id)+1 继续
        with pg_engine.begin() as conn:
            max_id = conn.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar()
            conn.execute(
                text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), {max_id})")
            )
        print(f"[{table}] 自增序列已重置为 {max_id}")

    print("=== 迁移全部完成 ===")


if __name__ == "__main__":
    main()
