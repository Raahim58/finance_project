from datetime import date, datetime

from pydantic import BaseModel, Field


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
    chunk_index: int
    chunk_text: str
    token_count: int
    score: float
    source_url: str | None
    page_number: int | None
    section_title: str | None
    metadata: dict
    citation: CitationResponse


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    symbols: list[str] | None = None
    sectors: list[str] | None = None
    document_types: list[str] | None = None
    date_from: date | None = None
    date_to: date | None = None
    portfolio_id: str | None = None
    limit: int = Field(default=5, ge=1, le=25)


class RagSearchResponse(BaseModel):
    chunks: list[RagChunkResponse]
    citations: list[CitationResponse]
    scores: list[float]
