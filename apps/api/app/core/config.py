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
    market_history_years: int = 5
    market_history_bootstrap_enabled: bool = True
    scheduled_research_enabled: bool = True
    research_report_limit_per_run: int = 20
    source_artifact_root: str = "./data/artifacts"
    embedding_dimensions: int = 384
    embedding_backend: str = "hash"
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    assistant_max_tool_iterations: int = 12
    assistant_max_tool_cost_units: int = 18
    assistant_max_retrieved_chunks: int = 8
    assistant_timeout_seconds: int = 30
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
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
