import os
import secrets
from typing import List, Literal, Optional

from pydantic import Field, model_validator

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 加载 backend_L 下的 .env 文件
    # extra="ignore"：.env 中仅供 docker-compose 使用的键（POSTGRES_* 等）不会导致校验失败
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    # ========== LLM 基础配置 ==========
    llm_base_url: str
    llm_api_key: str
    llm_model: str = "qwen-plus"
    llm_temperature: float = 0.7
    # 千问自带联网搜索（调研节点强制开启，其他节点不联网）
    llm_enable_search: bool = False
    # 是否开启模型思考模式（qwen3.x 默认 true，思考会显著拉长耗时；
    # 标题/评分/总结等固定格式任务关闭可大幅提速，默认关闭）
    llm_enable_thinking: bool = False
    # 开启思考模式的角色白名单（逗号分隔）；其余角色默认关闭思考以提速。
    # 例：reviewer（主编质量门深度评审）开思考，其他角色关思考
    llm_thinking_roles: str = "reviewer"

    @property
    def llm_thinking_roles_list(self) -> List[str]:
        """解析白名单：逗号分隔 -> 去空白 -> 列表"""
        return [r.strip() for r in self.llm_thinking_roles.split(",") if r.strip()]

    # ========== 各 Agent 模型配置（可选，不填则用默认 llm_model）==========
    llm_model_researcher: Optional[str] = None
    llm_model_title: Optional[str] = None
    llm_model_outliner: Optional[str] = None
    llm_model_writer: Optional[str] = None
    llm_model_reviewer: Optional[str] = None
    llm_model_image: Optional[str] = None

    # ========== 审稿配置 ==========
    enable_review: bool = True
    # 审稿不通过时，最多自动打回修改几次（含重新调研+重写）
    max_review_rounds: int = 2

    # ========== 搜索配置 ==========
    # 博查 Web Search API（国内直连、结构化返回来源与发布时间）；不填则搜索工具报错提示
    bocha_api_key: Optional[str] = None

    # ========== 配图配置 ==========
    unsplash_access_key: Optional[str] = None   # 方式A：搜索图片
    pexels_api_key: Optional[str] = None        # 方式A：搜索图片
    image_gen_model: str = "qwen-image-3.0-pro" # 方式B：AI 生成图片
    image_api_key: Optional[str] = None         # 配图专用 Key（不填用 llm_api_key）
    dashscope_workspace_id: Optional[str] = None
    image_save_dir: str = "/app/data/images"

    # ========== Database（开发环境 compose 内网服务名 postgresl）==========
    db_url: str = "postgresql+psycopg2://blog:lisiyao@postgresl:5432/blog_agent_L"

    # ========== Celery Redis（暂未使用，预留）==========
    redis_broker_url: str = "redis://127.0.0.1:6379/0"
    redis_result_backend: str = "redis://127.0.0.1:6379/0"

    # ========== Agent ==========
    agent_timeout: int = 120
    # 同一数据库内同时运行的生成子进程上限
    # 注意：每个任务含 5-10 次 LLM 调用，受 LLM API 限流约束，勿盲目调大
    agent_max_workers: int = Field(default=4, ge=1, le=64)
    agent_max_queued_jobs: int = Field(default=64, ge=1, le=10000)
    agent_job_lease_seconds: int = Field(default=90, ge=5, le=3600)
    agent_job_max_runtime_seconds: int = Field(default=1800, ge=30, le=14400)
    agent_job_max_attempts: int = Field(default=2, ge=1, le=5)
    agent_queue_poll_seconds: float = Field(default=1, ge=0.1, le=60)

    # A stage reservation and its durable job commit in the same transaction.
    free_daily_units: int = Field(default=10, ge=0)
    site_daily_units: int = Field(default=100, ge=0)
    free_daily_drafts: int = Field(default=20, ge=0)
    free_max_active_jobs: int = Field(default=1, ge=1, le=64)

    app_env: Literal["development", "test", "production"] = "development"
    registration_mode: Literal["auto", "test", "smtp", "closed"] = "auto"
    smtp_host: Optional[str] = None
    smtp_port: int = Field(default=465, ge=1, le=65535)
    smtp_transport: Literal["ssl", "starttls"] = "ssl"
    smtp_sender: Optional[str] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    auth_login_per_ip: int = Field(default=30, ge=1)
    auth_register_per_ip: int = Field(default=5, ge=1)
    auth_send_per_ip: int = Field(default=12, ge=1)

    @property
    def effective_registration(self) -> str:
        if self.registration_mode != "auto":
            return self.registration_mode
        if self.app_env != "production":
            return "test"
        return "smtp" if self.smtp_host and self.smtp_sender else "closed"

    @property
    def demo_recharge_enabled(self) -> bool:
        return self.app_env != "production" and self.effective_registration == "test"

    @model_validator(mode="after")
    def validate_deployment(self):
        if self.app_env == "production":
            if len(self.jwt_secret.encode()) < 32 or self.jwt_secret.startswith(("dev-secret", "change-me", "your-")):
                raise ValueError("生产环境需要独立的随机 JWT_SECRET（至少 32 字节）")
            if self.registration_mode == "test":
                raise ValueError("生产环境不能使用固定测试验证码")
        elif not self.jwt_secret or self.jwt_secret == "dev-secret-change-me-in-production":
            self.jwt_secret = secrets.token_urlsafe(48)
        if self.effective_registration == "smtp" and not (self.smtp_host and self.smtp_sender):
            raise ValueError("SMTP 注册需要配置 SMTP_HOST 和 SMTP_SENDER")
        if self.effective_registration == "test" and not (len(self.email_code_default) == 6 and self.email_code_default.isascii() and self.email_code_default.isdigit()):
            raise ValueError("测试验证码必须为六位数字")
        return self

    # ========== 用户认证配置 ==========
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 天
    email_code_default: str = "888888"


# Compose sets APP_ENV explicitly. A lowercase app_env inherited from an env file
# can coexist on Linux. Give the deployment setting deterministic precedence.
deployment_env = os.environ.get("APP_ENV")
settings = Settings(app_env=deployment_env) if deployment_env is not None else Settings()
