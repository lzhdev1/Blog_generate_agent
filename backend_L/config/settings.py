from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 加载 backend_L 下的 .env 文件
    # extra="ignore"：.env 中仅供 docker-compose 使用的键（POSTGRES_* 等）不会导致校验失败
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
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
    # 后台生成任务并发数（ThreadPoolExecutor worker 数）
    # 注意：每个任务含 5-10 次 LLM 调用，受 LLM API 限流约束，勿盲目调大
    agent_max_workers: int = 8

    # ========== 用户认证配置 ==========
    jwt_secret: str = "dev-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 天
    email_code_default: str = "888888"


settings = Settings()
