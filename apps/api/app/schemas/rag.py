from datetime import date, datetime

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DocumentResponse(BaseModel):
    id: str
    visibility: str
    portfolio_id: str | None
    symbol: str | None
    sector: str | None
    document_type: str
    title: str
    fiscal_year: int | None
    quarter: str | None
    source_name: str
    source_url: str | None
    local_file_path: str | None
    content_hash: str
    published_date: date | None
    parsed_at: datetime | None
    status: str
    source_tier: int
    data_status: str
    error_message: str | None
    created_at: datetime


class DocumentIngestRequest(BaseModel):
    text: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=255)
    document_type: str = Field(min_length=1, max_length=80)
    symbol: str | None = Field(default=None, max_length=30)
    sector: str | None = Field(default=None, max_length=120)
    fiscal_year: int | None = None
    quarter: str | None = Field(default=None, max_length=20)
    source_name: str = Field(default="manual", max_length=120)
    source_url: str | None = Field(default=None, max_length=500)
    published_date: date | None = None
    visibility: str = Field(default="private", pattern="^(public|private)$")
    portfolio_id: str | None = None


class CitationResponse(BaseModel):
    id: str
    document_id: str
    chunk_id: str | None
    source_name: str
    source_url: str | None
    title: str
    page_number: int | None
    quote_snippet: str | None
    created_at: datetime


class RagChunkResponse(BaseModel):
    id: str
    document_id: str
    symbol: str | None
    document_type: str
    chunk_index: int
    chunk_text: str
    token_count: int
    score: float
    semantic_score: float
    lexical_score: float
    rrf_score: float
    source_url: str | None
    page_number: int | None
    section_title: str | None
    metadata: dict
    citation: CitationResponse
    citation_eligible: bool


class RagSearchAudit(BaseModel):
    plan: dict
    semantic_candidates: int
    lexical_candidates: int
    fused_candidates: int
    admitted_candidates: int
    rejected_by_reason: dict[str, int]
    embedding_model: str
    rrf_k: int


class RagDisambiguation(BaseModel):
    symbols: list[str]
    reason: str


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    symbols: list[str] | None = None
    sectors: list[str] | None = None
    document_types: list[str] | None = None
    date_from: date | None = None
    date_to: date | None = None
    time_horizon: Literal["week", "month", "quarter", "six_months", "year", "all"] | None = None
    portfolio_id: str | None = None
    limit: int = Field(default=5, ge=1, le=25)

    @model_validator(mode="after")
    def validate_date_range(self) -> "RagSearchRequest":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        if self.time_horizon and (self.date_from or self.date_to):
            raise ValueError("time_horizon cannot be combined with explicit date bounds")
        return self


class RagSearchResponse(BaseModel):
    status: Literal["ok", "insufficient_evidence", "needs_disambiguation"] = "ok"
    chunks: list[RagChunkResponse]
    citations: list[CitationResponse]
    scores: list[float]
    audit: RagSearchAudit
    disambiguation: RagDisambiguation | None = None
