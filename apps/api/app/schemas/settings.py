from pydantic import BaseModel, Field


class PreferencesResponse(BaseModel):
    default_llm_provider: str
    risk_tolerance: str
    investment_horizon: str
    preferred_analysis_mode: str
    preferred_sectors: list[str]
    avoided_sectors: list[str]
    notification_preferences: dict
    followup_frequency: str


class PreferencesUpdate(BaseModel):
    default_llm_provider: str | None = None
    risk_tolerance: str | None = Field(default=None, pattern="^(conservative|balanced|aggressive)$")
    investment_horizon: str | None = Field(default=None, pattern="^(short-term|medium-term|long-term)$")
    preferred_analysis_mode: str | None = Field(
        default=None,
        pattern="^(statistical|policy/government|geopolitical|fundamentals|technical/market trend|combined)$",
    )
    preferred_sectors: list[str] | None = None
    avoided_sectors: list[str] | None = None
    notification_preferences: dict | None = None
    followup_frequency: str | None = Field(default=None, pattern="^(frequently|normally|minimally)$")


class LLMKeyCreate(BaseModel):
    provider: str = Field(min_length=2, max_length=50)
    api_key: str = Field(min_length=4)
    default_model: str | None = None


class LLMKeyTest(BaseModel):
    provider: str = Field(min_length=2, max_length=50)
    api_key: str = Field(min_length=4)
    default_model: str | None = None


class LLMKeyResponse(BaseModel):
    id: str
    provider: str
    masked_api_key: str
    default_model: str | None = None
    is_active: bool
    last_used_at: str | None = None


class LLMKeyTestResponse(BaseModel):
    provider: str
    valid: bool
    message: str
