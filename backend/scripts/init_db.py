from src.blog_agent.db.session import engine, Base
from src.blog_agent.db import models


def init_db():
    Base.metadata.create_all(bind=engine)
    print("数据库表创建完成")


if __name__ == "__main__":
    init_db()
