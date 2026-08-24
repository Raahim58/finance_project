from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PRODUCTION_APP_ENVS = {"production", "prod"}


class Settings(BaseSettings):
    app_name: str = "psx-ai-portfolio-agent"
    app_env: str = "local"
    database_url: str = "sqlite+pysqlite:///./psx_ai_local.db"
    test_database_url: str = "sqlite+pysqlite:///:memory:"
    database_pool_size: int = Field(default=24, ge=1, le=100)
    database_max_overflow: int = Field(default=8, ge=0, le=100)
    jwt_secret_key: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)
    enable_demo_access: bool = False
    demo_access_token: str = ""
    demo_access_email: str = "portfolio.manager@example.com"
    allow_mock_in_production: bool = False
    encryption_key: str = "dev-only-invalid-key"
    market_data_mode: str = "mock"
    market_data_refresh_seconds: int = 300
    phase2_refill_seconds: int = Field(default=2, ge=1, le=60)
    phase2_max_retries: int = Field(default=3, ge=0, le=10)
    phase2_retry_backoff_seconds: int = Field(default=300, ge=1, le=86400)
    phase2_broad_queue_target: int = Field(default=40, ge=1, le=1000)
    phase2_history_queue_target: int = Field(default=96, ge=1, le=5000)
    phase2_download_queue_target: int = Field(default=24, ge=1, le=1000)
    phase2_extract_queue_target: int = Field(default=12, ge=1, le=1000)
    phase2_catalog_refresh_hours: int = Field(default=6, ge=1, le=168)
    market_history_years: int = 5
    market_history_bootstrap_enabled: bool = True
    scheduled_research_enabled: bool = True
    macro_ingestion_enabled: bool = False
    macro_scheduler_seconds: int = Field(default=30, ge=30, le=86400)
    macro_queue_target: int = Field(default=8, ge=1, le=100)
    macro_history_start_year: int = Field(default=2000, ge=1960, le=2100)
    fred_api_key: str = ""
    eia_api_key: str = ""
    research_report_limit_per_run: int = 20
    source_artifact_root: str = "./data/artifacts"
    embedding_dimensions: int = 384
    embedding_backend: str = "sentence_transformers"
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_index_version: int = Field(default=2, ge=1)
    retrieval_rrf_k: int = Field(default=60, ge=1, le=1000)
    retrieval_candidate_depth: int = Field(default=50, ge=10, le=500)
    retrieval_min_semantic_score: float = Field(default=0.25, ge=-1, le=1)
    retrieval_min_lexical_score: float = Field(default=0.50, ge=0, le=1)
    assistant_max_tool_iterations: int = 12
    assistant_max_tool_cost_units: int = 18
    assistant_max_retrieved_chunks: int = 8
    assistant_timeout_seconds: int = 30
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    evidence_enabled: bool = False
    evidence_scheduler_seconds: int = Field(default=30, ge=5, le=3600)
    evidence_discovery_queue_target: int = Field(default=20, ge=1, le=1000)
    evidence_fetch_queue_target: int = Field(default=80, ge=1, le=5000)
    evidence_parse_queue_target: int = Field(default=80, ge=1, le=5000)
    evidence_index_queue_target: int = Field(default=40, ge=1, le=2000)
    evidence_historical_queue_target: int = Field(default=10, ge=1, le=500)
    evidence_historical_batch_candidates: int = Field(default=25, ge=1, le=50)
    evidence_historical_fetch_budget: int = Field(default=100, ge=1, le=5000)
    evidence_historical_storage_budget_mb: int = Field(default=250, ge=1, le=10240)
    evidence_historical_live_backlog_reserve: int = Field(default=1, ge=0, le=1000)
    evidence_historical_expansion_healthy_days: int = Field(default=7, ge=1, le=30)
    evidence_stage_lease_seconds: int = Field(default=900, ge=60, le=86400)
    evidence_max_retries: int = Field(default=3, ge=0, le=10)
    evidence_retry_backoff_seconds: int = Field(default=60, ge=1, le=86400)
    evidence_circuit_failure_threshold: int = Field(default=5, ge=1, le=100)
    evidence_circuit_open_seconds: int = Field(default=900, ge=60, le=86400)
    evidence_candidate_retention_days: int = Field(default=45, ge=1, le=3650)
    evidence_spool_retention_hours: int = Field(default=24, ge=1, le=168)
    evidence_pass4_official_enabled: bool = False
    evidence_pass4_breadth_enabled: bool = False
    evidence_psx_announcement_history_enabled: bool = False
    evidence_canary_discovery_daily: int = Field(default=2000, ge=1, le=100000)
    evidence_canary_fetch_daily: int = Field(default=250, ge=1, le=10000)
    evidence_canary_selected_daily: int = Field(default=75, ge=1, le=5000)
    evidence_canary_storage_daily_mb: int = Field(default=1536, ge=1, le=102400)
    evidence_canary_storage_seven_day_mb: int = Field(default=10240, ge=1, le=512000)
    evidence_canary_fetch_ready_target: int = Field(default=120, ge=1, le=5000)
    evidence_contact_email: str = "evidence-ops@example.invalid"
    evidence_sec_edgar_ciks: str = ""
    screening_completeness_threshold: float = Field(default=0.70, ge=0, le=1)
    screening_promotion_percentile: float = Field(default=0.82, ge=0, le=1)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    auto_create_tables: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("market_data_mode")
    @classmethod
    def validate_market_data_mode(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"mock", "psxdata", "yahoo", "auto", "dps", "vendor"}:
            raise ValueError("MARKET_DATA_MODE must be one of: mock, psxdata, yahoo, auto, dps, vendor")
        return normalized

    @field_validator("embedding_backend")
    @classmethod
    def validate_embedding_backend(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"hash", "sentence_transformers"}:
            raise ValueError("EMBEDDING_BACKEND must be hash or sentence_transformers")
        return normalized

    @model_validator(mode="after")
    def guard_mock_data_in_production(self) -> "Settings":
        if self.app_env.lower().strip() in PRODUCTION_APP_ENVS and self.bcrypt_rounds < 12:
            raise ValueError("BCRYPT_ROUNDS must be at least 12 in production")
        if self.app_env.lower().strip() in PRODUCTION_APP_ENVS and self.market_data_mode == "mock" and not self.allow_mock_in_production:
            raise ValueError(
                "Refusing to start with APP_ENV=production and MARKET_DATA_MODE=mock: this would silently serve "
                "synthetic/demo market data as if it were observed. Set MARKET_DATA_MODE to a live provider, or set "
                "ALLOW_MOCK_IN_PRODUCTION=true if this is an explicit, disclosed exception."
            )
        return self

    @property
    def is_synthetic_environment(self) -> bool:
        """Whether configured external-world data is intentionally synthetic.

        Localhost is a deployment location, not data provenance.  A local app in
        ``auto``/live mode must therefore apply the same observed-data rules as a
        hosted deployment.
        """
        return self.market_data_mode == "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
