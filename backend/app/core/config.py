"""
Application Settings — Pydantic-Settings V2
=============================================
Centralized, type-safe configuration loaded exclusively from environment
variables and the ``.env`` file. NEVER hardcode secrets anywhere else.

Usage:
    from app.core.config import settings

    db_url = settings.DATABASE_URL
    secret  = settings.SECRET_KEY

The ``@lru_cache`` ensures a single Settings instance is created once per
process, preventing repeated disk I/O on every import.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application configuration, loaded from environment / .env file.

    Pydantic-Settings V2 reads from:
        1. Actual environment variables (highest priority)
        2. Variables declared in the `.env` file
        3. Field defaults (lowest — only safe non-secret defaults)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,    # Env vars are case-insensitive
        extra="ignore",          # Ignore extra variables in .env
    )

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    APP_ENV: str = Field(default="development", pattern=r"^(development|staging|production)$")
    APP_NAME: str = Field(default="Agromaly API")
    APP_VERSION: str = Field(default="0.1.0")
    DEBUG: bool = Field(default=False)

    # ------------------------------------------------------------------
    # Security — JWT
    # ------------------------------------------------------------------
    SECRET_KEY: str = Field(
        ...,  # Required — no default
        min_length=32,
        description="Long random hex string for JWT signing. Generate: python -c \"import secrets; print(secrets.token_hex(64))\"",
    )
    ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, ge=5, le=1440)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, ge=1, le=30)

    # ------------------------------------------------------------------
    # Database — PostgreSQL + PostGIS
    # ------------------------------------------------------------------
    POSTGRES_USER: str = Field(default="agromaly")
    POSTGRES_PASSWORD: str = Field(..., min_length=8)
    POSTGRES_DB: str = Field(default="agromaly_db")
    POSTGRES_HOST: str = Field(default="db")
    POSTGRES_PORT: int = Field(default=5432)

    # Assembled async URL for SQLAlchemy (asyncpg driver)
    DATABASE_URL: str = Field(default="")
    # Assembled sync URL for Alembic (psycopg2 driver)
    DATABASE_SYNC_URL: str = Field(default="")

    # ------------------------------------------------------------------
    # Redis — Celery
    # ------------------------------------------------------------------
    REDIS_HOST: str = Field(default="redis")
    REDIS_PORT: int = Field(default=6379)
    REDIS_PASSWORD: str = Field(..., min_length=8)
    CELERY_BROKER_URL: str = Field(default="")
    CELERY_RESULT_BACKEND: str = Field(default="")

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_EMBEDDING_MODEL: str = Field(default="text-embedding-3-small")
    OPENAI_CHAT_MODEL: str = Field(default="gpt-4o-mini")

    # ------------------------------------------------------------------
    # Weather API
    # ------------------------------------------------------------------
    WEATHER_API_BASE_URL: str = Field(default="https://api.open-meteo.com/v1")
    WEATHER_API_KEY: str = Field(default="")

    # ------------------------------------------------------------------
    # Vector Store
    # ------------------------------------------------------------------
    CHROMA_PERSIST_DIRECTORY: str = Field(default="/app/data/chroma")

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    ALLOWED_ORIGINS: str = Field(default="http://localhost:3000,http://localhost:8081")

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def assemble_db_urls(self) -> "Settings":
        """Auto-assemble DATABASE_URL / DATABASE_SYNC_URL if not explicitly set."""
        base = (
            f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
        if not self.DATABASE_URL:
            object.__setattr__(self, "DATABASE_URL", f"postgresql+asyncpg://{base}")
        if not self.DATABASE_SYNC_URL:
            object.__setattr__(self, "DATABASE_SYNC_URL", f"postgresql+psycopg2://{base}")
        return self

    @model_validator(mode="after")
    def assemble_redis_urls(self) -> "Settings":
        """Auto-assemble Celery URLs if not explicitly set."""
        base = f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}"
        if not self.CELERY_BROKER_URL:
            object.__setattr__(self, "CELERY_BROKER_URL", f"{base}/0")
        if not self.CELERY_RESULT_BACKEND:
            object.__setattr__(self, "CELERY_RESULT_BACKEND", f"{base}/1")
        return self

    # ------------------------------------------------------------------
    # Computed Properties
    # ------------------------------------------------------------------

    @property
    def allowed_origins_list(self) -> List[str]:
        """Parse comma-separated ALLOWED_ORIGINS into a list."""
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance.

    The cache is invalidated only when the process restarts, making this
    safe for use in FastAPI ``Depends``.

    Usage in endpoints::

        from fastapi import Depends
        from app.core.config import get_settings, Settings

        def my_endpoint(cfg: Settings = Depends(get_settings)):
            ...
    """
    return Settings()  # type: ignore[call-arg]


# Module-level singleton for non-DI usage (imports, Celery, etc.)
settings: Settings = get_settings()
