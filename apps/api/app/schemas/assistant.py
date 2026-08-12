from datetime import datetime

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str = Field(default="Portfolio research", min_length=1, max_length=255)
    portfolio_id: str | None = None


class AssistantMessageCreate(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    portfolio_id: str | None = None
    instrument_id: str | None = None
    provider: str | None = None
    model: str | None = None


class AssistantResponse(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    uncertainty: list[str]
    calculated_evidence: list[dict[str, object]]
    source_citations: list[dict[str, object]]
    freshness_warnings: list[str]
    tool_trace: list[dict[str, object]]
    synthesis: dict[str, object]
    created_at: datetime
