from functools import lru_cache
from typing import Literal

from pydantic import AnyUrl, Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────
    app_name: str = "AI Backend System"
    app_version: str = "1.0.0"
    environment: Literal["development", "staging", "production", "testing"] = "development"
    debug: bool = False
    secret_key: str = Field(..., min_length=32)

    # ── Server ───────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    reload: bool = False

    # ── Database ─────────────────────────────────────────────
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # ── Redis ────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 300

    # ── JWT ──────────────────────────────────────────────────
    jwt_secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # ── OpenAI ───────────────────────────────────────────────
    openai_api_key: str
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_max_tokens: int = 4096
    openai_temperature: float = 0.1
    llm_request_timeout: int = 60

    # ── File Upload ──────────────────────────────────────────
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 100
    allowed_extensions: str = "csv,json,xlsx"

    # ── Celery ───────────────────────────────────────────────
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── Rate Limiting ─────────────────────────────────────────
    rate_limit_per_minute: int = 60
    rate_limit_ai_per_minute: int = 10

    # ── Logging ──────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    @property
    def allowed_extensions_list(self) -> list[str]:
        return [ext.strip() for ext in self.allowed_extensions.split(",")]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @field_validator("database_url")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v.startswith(("postgresql", "sqlite")):
            raise ValueError("Only PostgreSQL and SQLite are supported")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — import this everywhere."""
    return Settings()


settings = get_settings()
