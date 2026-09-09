from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    # 加载backend下的.env文件
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ========== LLM 基础配置 ==========
    llm_base_url: str
    llm_api_key: str
    llm_model: str = "qwen-plus"
    llm_temperature: float = 0.7
    # 千问自带联网搜索（全局开关，researcher 节点会强制开启）
    llm_enable_search: bool = False

    # ========== 各 Agent 模型配置（可选，不填则用默认 llm_model）==========
    # 研究员：速度快、便宜
    llm_model_researcher: Optional[str] = None
    # 大纲师：平衡质量和速度
    llm_model_outliner: Optional[str] = None
    # 写手：正文生成需要质量
    llm_model_writer: Optional[str] = None
    # 审稿：需要最强的推理和判断能力，建议用更强的模型
    llm_model_reviewer: Optional[str] = None
    # 排版师：简单任务，用便宜的
    llm_model_formatter: Optional[str] = None

    # ========== 审稿配置 ==========
    # 是否启用审稿循环（关闭后写完正文直接配图/格式化，速度更快）
    enable_review: bool = True
    # 审稿不通过时，最多自动修改几次
    max_review_rounds: int = 2

    # ========== 配图配置 ==========
    # 图片网站API（方式A：搜索图片）
    unsplash_access_key: Optional[str] = None   # Unsplash API Key
    pexels_api_key: Optional[str] = None        # Pexels API Key
    # AI图片生成（方式B：百炼通义万相）
    image_gen_model: str = "wanx2.1-t2i-turbo"  # 图片生成模型

    # Database
    db_url: str = "sqlite:///./blog_agent.db"

    # Celery Redis
    redis_broker_url: str = "redis://127.0.0.1:6379/0"
    redis_result_backend: str = "redis://127.0.0.1:6379/0"

    # Agent
    agent_timeout: int = 120


settings = Settings()
