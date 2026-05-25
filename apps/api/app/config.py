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
    # Which open-API source the live heritage adapter routes through.
    # ``jangseogak`` (default) uses the 장서각 endpoint wired in PR #33;
    # ``koreanstudies`` uses the 한국학자료포털 (kostma.aks.ac.kr) open
    # API (PR #35); ``nlk`` uses the 국립중앙도서관 (nl.go.kr) Open
    # API — NLK requires ``NLK_API_KEY`` (apply at
    # https://www.nl.go.kr/NL/contents/N31101030500.do); without a key the
    # factory degrades to the mock matcher even when ``HERITAGE_PROVIDER=live``.
    # ``gihohak`` uses the 기호유학 고문헌 통합정보시스템 (giho.cnu.ac.kr)
    # Open API operated by 충남대 — fully open, no key required (same as
    # 장서각 / 한국학자료포털).
    # ``multi`` fan-ins across multiple sources at once — the participating
    # sources are listed in ``HERITAGE_MULTI_SOURCES`` (comma-separated).
    # See todo.md §1.3.1 for the broader source roadmap.
    heritage_live_source: Literal["jangseogak", "koreanstudies", "nlk", "gihohak", "multi"] = (
        "jangseogak"
    )
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
    # Gemini live LLM adapter (spec §6). Defaults match the spec literally
    # (``gemini-2.5-pro``, max tokens 4000 / 2000, temperatures 0.7 / 0.1).
    # The base URL + timeout are overridable for staging mirrors and for
    # tests that point at a recorded fixture server.
    gemini_model: str = "gemini-2.5-pro"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    gemini_request_timeout_seconds: float = 30.0
    gemini_recipe_max_tokens: int = 4000
    gemini_translate_max_tokens: int = 2000
    gemini_recipe_temperature: float = 0.7
    gemini_translate_temperature: float = 0.1
    # 장서각 Digital Archive Open API: https://jsg.aks.ac.kr/api/help
    # The live endpoint is fully open (no API key required), so the key
    # field stays for forward-compatibility only — the active live mode
    # uses ``jangseogak_base_url`` and no auth header.
    jangseogak_api_key: str = ""
    jangseogak_base_url: str = "https://jsg.aks.ac.kr/api"
    # 한국학자료포털 (한국학중앙연구원) open API: https://kostma.aks.ac.kr
    # Fully open (no API key required), exposed via ``/OpenAPI/request.aspx``.
    # The key field stays for forward-compatibility only.
    koreanstudies_api_key: str = ""
    koreanstudies_base_url: str = "https://kostma.aks.ac.kr"
    # 국립중앙도서관 (NLK) Open API: https://www.nl.go.kr
    # Requires an API key (apply at
    # https://www.nl.go.kr/NL/contents/N31101030500.do, admin approval).
    # Without ``NLK_API_KEY`` the factory keeps the mock matcher even when
    # ``HERITAGE_LIVE_SOURCE=nlk`` — see `app/services/heritage/__init__.py`.
    nlk_api_key: str = ""
    nlk_base_url: str = "https://www.nl.go.kr"
    # 기호유학 고문헌 통합정보시스템 (충남대): http://giho.cnu.ac.kr
    # Fully open (no API key required), exposed via
    # ``/api/literature/search.do``. Endpoint defaults to HTTP because the
    # upstream TLS chain has historically been incomplete; operators can
    # override to HTTPS if/when CNU rolls out a valid cert.
    gihohak_base_url: str = "http://giho.cnu.ac.kr"
    # Comma-separated list of source names used by
    # ``MultiSourceHeritageAdapter`` when ``HERITAGE_LIVE_SOURCE=multi``.
    # Allowed values: ``jangseogak``, ``koreanstudies``, ``nlk``,
    # ``gihohak``. Unknown / unauthenticated sources (e.g. ``nlk`` without
    # ``NLK_API_KEY``) are silently skipped at boot — the multi-adapter
    # only refuses to start when **zero** sources remain after filtering.
    # ``nlk`` is omitted from the default so the multi pipeline boots
    # without a key; add it once ``NLK_API_KEY`` is provisioned.
    heritage_multi_sources: str = "jangseogak,koreanstudies,gihohak"
    nfm_api_key: str = ""
    culture_api_key: str = ""
    toss_secret_key: str = ""
    toss_client_key: str = ""
    naver_datalab_client_id: str = ""
    naver_datalab_client_secret: str = ""
    naver_datalab_base_url: str = "https://openapi.naver.com"
    naver_shopping_insight_category_code: str = "50000006"

    cors_allow_origins: str = "http://localhost:5173,http://localhost:3000"

    # ------------------------------------------------------------------
    # Vertex AI embedding + Vector Search (per-source namespace indexing)
    # ------------------------------------------------------------------
    # When ``EMBEDDING_PROVIDER=live`` the API calls Vertex AI's
    # publisher-model ``:predict`` endpoint for ``text-embedding-005``
    # (or whichever ``VERTEX_EMBEDDING_MODEL`` overrides). Missing
    # ``VERTEX_PROJECT_ID`` / ``GOOGLE_OAUTH_ACCESS_TOKEN`` degrades to
    # the mock embedder at boot — same contract as the heritage/LLM
    # factories. See ``app/services/embeddings/__init__.py``.
    embedding_provider: Literal["mock", "live"] = "mock"
    # ``VECTOR_SEARCH_PROVIDER=live`` enables the Vertex AI Vector
    # Search REST adapter. Per-namespace ``VERTEX_VECTOR_INDEX_*`` env
    # vars wire each source to its own Vertex index / deployed index
    # / index endpoint — see ``app/services/vector_search/__init__.py``.
    vector_search_provider: Literal["mock", "live"] = "mock"
    vertex_project_id: str = ""
    vertex_location: str = "us-central1"
    vertex_embedding_model: str = "text-embedding-005"
    vertex_embedding_dimension: int = 768
    # Comma-separated list of source-keyed namespaces used by
    # ``HeritageIndexer`` / ``VertexAIVectorSearchAdapter``. Matches
    # the heritage roadmap in ``todo.md`` §1.3.1.
    vertex_vector_namespaces: str = "jangseogak,koreanstudies,nlk,gihohak,nihc"

    # ------------------------------------------------------------------
    # Recipe-generate heritage retrieval mode
    # ------------------------------------------------------------------
    # ``keyword`` (default) — call the keyword heritage adapter only
    # (existing behaviour, byte-identical to pre-hybrid code paths).
    # ``hybrid`` — wrap the keyword adapter with
    # :class:`HybridHeritageAdapter`, which also queries
    # :class:`HeritageIndexer.query_all_sources` and blends both
    # layers' results. Requires no extra credentials: if the vector
    # store is mock or empty the semantic side simply contributes
    # nothing and recipe-generate keeps working.
    heritage_retrieval_mode: Literal["keyword", "hybrid"] = "keyword"
    # Blend weight for hybrid retrieval — keyword side. The semantic
    # side gets ``1 - heritage_hybrid_keyword_weight``. 0.6 gives
    # keyword precision the edge by default while keeping semantic
    # recall in play. Must be in [0, 1].
    heritage_hybrid_keyword_weight: float = 0.6
    # How many neighbours to ask the semantic side for. The hybrid
    # adapter eventually trims to the caller's ``limit``, but pulls
    # more from the index so weak semantic-only candidates still get
    # a chance against strong keyword hits after blending.
    heritage_hybrid_semantic_top_k: int = 20

    free_plan_monthly_recipe_quota: int = 3
    free_plan_hourly_rate_limit: int = 10

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def heritage_multi_sources_list(self) -> list[str]:
        return [s.strip() for s in self.heritage_multi_sources.split(",") if s.strip()]

    @property
    def vertex_vector_namespaces_list(self) -> list[str]:
        return [s.strip() for s in self.vertex_vector_namespaces.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
