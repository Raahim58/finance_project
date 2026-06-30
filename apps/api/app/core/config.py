from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "psx-ai-portfolio-agent"
    app_env: str = "local"
    database_url: str = "sqlite+pysqlite:///./psx_ai_local.db"
    test_database_url: str = "sqlite+pysqlite:///:memory:"
    jwt_secret_key: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    encryption_key: str = "dev-only-invalid-key"
    market_data_mode: str = "mock"
    market_data_refresh_seconds: int = 300
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
        if normalized not in {"mock", "dps", "vendor"}:
            raise ValueError("MARKET_DATA_MODE must be one of: mock, dps, vendor")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
