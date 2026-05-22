"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Values come from env vars (.env file in dev)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = "sqlite:///./dev.db"

    jwt_secret_key: str = "dev-only-do-not-use-in-production"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 30
    jwt_algorithm: str = "HS256"

    llm_provider: Literal["mock", "live"] = "mock"
    heritage_provider: Literal["mock", "live"] = "mock"
    payments_provider: Literal["mock", "live"] = "mock"

    gemini_api_key: str = ""
    jangseogak_api_key: str = ""
    nfm_api_key: str = ""
    culture_api_key: str = ""
    toss_secret_key: str = ""
    toss_client_key: str = ""

    cors_allow_origins: str = "http://localhost:5173,http://localhost:3000"

    free_plan_monthly_recipe_quota: int = 3
    free_plan_hourly_rate_limit: int = 10

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
