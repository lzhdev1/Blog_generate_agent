import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config.settings import settings
from src.blog_agent.api.v1.articles import router as articles_router
from src.blog_agent.api.v1.auth import router as auth_router
from src.blog_agent.api.v1.blog import router as blog_router
from src.blog_agent.api.v1.notifications import router as notifications_router
from src.blog_agent.db.session import init_db

app = FastAPI(
    title="Blog Agent L",
    description="LangGraph 多 Agent 博客生成系统（重构版后端）",
    version="0.1.0",
)

# 开发环境 CORS：允许新前端（vite dev 5174）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 启动时建表（开发环境 create_all）
init_db()

# 配图静态文件服务：持久化后的本地图片通过 /images/<文件名> 访问
os.makedirs(settings.image_save_dir, exist_ok=True)
app.mount("/images", StaticFiles(directory=settings.image_save_dir), name="images")

# 注册路由
app.include_router(blog_router)
app.include_router(auth_router)
app.include_router(articles_router)
app.include_router(notifications_router)


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "service": "blog-agent-L", "version": "0.1.0"}
