"""Operator-controlled ceilings for one submitted Agent stage."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelLimits(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MODEL_LIMIT_", env_file=".env", extra="ignore")

    enabled: bool = True
    ai_images_enabled: bool = True
    model_calls: int = Field(24, ge=0, le=100)
    tool_requests: int = Field(40, ge=0, le=200)
    images: int = Field(3, ge=0, le=12)
    stage_seconds: int = Field(600, ge=1, le=1800)
    request_seconds: int = Field(90, ge=1, le=180)
    sdk_retries: int = Field(0, ge=0, le=1)
    input_bytes: int = Field(192_000, ge=1024, le=512_000)
    output_tokens: int = Field(8192, ge=1, le=16_384)
    image_bytes: int = Field(8 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024)


limits = ModelLimits()
