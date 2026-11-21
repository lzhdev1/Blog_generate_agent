import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from config.settings import settings
from src.blog_agent.api.http_limits import install_http_limits
from src.blog_agent.api.v1.articles import router as articles_router
from src.blog_agent.api.v1.auth import router as auth_router
from src.blog_agent.api.v1.blog import router as blog_router
from src.blog_agent.api.v1.revisions import router as revision_router
from src.blog_agent.api.v1.media import router as media_router
from src.blog_agent.api.v1.notifications import router as notifications_router
from src.blog_agent.db.session import get_db, init_db
from src.blog_agent.service.job_worker import WorkerSupervisor


@asynccontextmanager
async def lifespan(app):
    init_db()
    os.makedirs(settings.image_save_dir, exist_ok=True)
    supervisor = WorkerSupervisor()
    app.state.supervisor = supervisor
    supervisor.start()
    try:
        yield
    finally:
        supervisor.stop()

app = FastAPI(
    title="Blog Agent L",
    description="LangGraph 多 Agent 博客生成系统（重构版后端）",
    version="0.1.0",
    lifespan=lifespan,
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

install_http_limits(app)
app.include_router(media_router)

# 注册路由
app.include_router(blog_router)
app.include_router(revision_router)
app.include_router(auth_router)
app.include_router(articles_router)
app.include_router(notifications_router)


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "service": "blog-agent-L", "version": "0.1.0"}


@app.get("/api/v1/ready")
def ready(request: Request, db: Session = Depends(get_db)):
    supervisor = getattr(request.app.state, "supervisor", None)
    unavailable = HTTPException(503, "服务尚未就绪", headers={"Retry-After": "5"})
    if not supervisor or not supervisor.ready:
        raise unavailable
    try:
        db.execute(select(1))
    except SQLAlchemyError:
        raise unavailable from None
    return {"status": "ready"}
