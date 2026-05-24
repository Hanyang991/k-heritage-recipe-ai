"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

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
    trends_provider: Literal["mock", "live"] = "mock"
    trends_discovery_source: Literal["curated", "shopping_insight", "open"] = "curated"
    trends_open_google_enabled: bool = True
    google_trends_geo: str = "KR"
    google_trends_hl: str = "ko-KR"
    trends_open_naver_news_enabled: bool = True
    naver_news_seed_queries: str = "디저트 신상,K-디저트,신메뉴 카페,트렌드 음료,한식 디저트"
    naver_news_display_per_query: int = 50
    naver_news_min_article_count: int = 2
    trends_open_llm_enabled: bool = False
    gemini_trends_model: str = "gemini-2.5-flash"
    gemini_trends_target_count: int = 30
    gemini_trends_base_url: str = "https://generativelanguage.googleapis.com"
    # Daily scheduler trigger hour in UTC. Default 18 UTC = 03:00 KST so the
    # new top-N is ready by the time East Asian users open the dashboard.
    trends_refresh_hour_utc: int = 18

    gemini_api_key: str = ""
    # 장서각 Digital Archive Open API: https://jsg.aks.ac.kr/api/help
    # The live endpoint is fully open (no API key required), so the key
    # field stays for forward-compatibility only — the active live mode
    # uses ``jangseogak_base_url`` and no auth header.
    jangseogak_api_key: str = ""
    jangseogak_base_url: str = "https://jsg.aks.ac.kr/api"
    nfm_api_key: str = ""
    culture_api_key: str = ""
    toss_secret_key: str = ""
    toss_client_key: str = ""
    naver_datalab_client_id: str = ""
    naver_datalab_client_secret: str = ""
    naver_datalab_base_url: str = "https://openapi.naver.com"
    naver_shopping_insight_category_code: str = "50000006"

    cors_allow_origins: str = "http://localhost:5173,http://localhost:3000"

    free_plan_monthly_recipe_quota: int = 3
    free_plan_hourly_rate_limit: int = 10

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
