import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config.settings import settings
from src.blog_agent.api.v1.auth import router as auth_router
from src.blog_agent.api.v1.blog import router as blog_router
from src.blog_agent.api.v1.articles import router as articles_router
from src.blog_agent.api.v1.notifications import router as notifications_router

app = FastAPI(
    title="博客生成 Agent API",
    description="AI 自动生成博客的后端服务",
    version="0.2.0",
)

# 跨域配置：允许前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # 开发阶段允许所有来源，生产环境改成前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 配图静态文件服务：持久化后的本地图片通过 /images/<文件名> 访问
os.makedirs(settings.image_save_dir, exist_ok=True)
app.mount("/images", StaticFiles(directory=settings.image_save_dir), name="images")

# 注册路由
app.include_router(auth_router)
app.include_router(blog_router)
app.include_router(articles_router)
app.include_router(notifications_router)


@app.get("/", summary="健康检查")
def health_check():
    """服务启动后访问根路径，确认服务正常运行"""
    return {"status": "ok", "message": "博客生成 Agent 服务运行中"}
