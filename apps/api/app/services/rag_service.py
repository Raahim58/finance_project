import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Citation, Document, DocumentChunk, DocumentPage
from app.models.market import Company
from app.schemas.rag import (
    CitationResponse,
    DocumentIngestRequest,
    DocumentResponse,
    RagChunkResponse,
    RagSearchRequest,
    RagSearchResponse,
)

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%-]*")
EMBEDDING_DIMENSIONS = 64
CHUNK_TOKENS = 180
CHUNK_OVERLAP = 40


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    text: str


def normalize_symbol(symbol: str | None) -> str | None:
    return symbol.upper() if symbol else None


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_text(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        vector[bucket] += 1.0
    magnitude = math.sqrt(sum(value * value for value in vector))
    if not magnitude:
        return vector
    return [value / magnitude for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def keyword_score(query_tokens: set[str], chunk_text: str) -> float:
    if not query_tokens:
        return 0.0
    chunk_tokens = set(tokenize(chunk_text))
    return len(query_tokens.intersection(chunk_tokens)) / len(query_tokens)


def chunk_page_text(text: str, page_number: int) -> list[tuple[str, int]]:
    tokens = tokenize(text)
    if not tokens:
        return []
    chunks: list[tuple[str, int]] = []
    start = 0
    while start < len(tokens):
        end = min(start + CHUNK_TOKENS, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append((" ".join(chunk_tokens), page_number))
        if end == len(tokens):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def first_snippet(text: str, max_chars: int = 260) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 3]}..."


def serialize_document(document: Document) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        symbol=document.symbol,
        sector=document.sector,
        document_type=document.document_type,
        title=document.title,
        fiscal_year=document.fiscal_year,
        quarter=document.quarter,
        source_name=document.source_name,
        source_url=document.source_url,
        local_file_path=document.local_file_path,
        content_hash=document.content_hash,
        published_date=document.published_date,
        parsed_at=document.parsed_at,
        status=document.status,
        error_message=document.error_message,
        created_at=document.created_at,
    )


def serialize_citation(citation: Citation) -> CitationResponse:
    return CitationResponse(
        id=citation.id,
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        source_name=citation.source_name,
        source_url=citation.source_url,
        title=citation.title,
        page_number=citation.page_number,
        quote_snippet=citation.quote_snippet,
        created_at=citation.created_at,
    )


def find_company(db: Session, symbol: str | None) -> Company | None:
    if not symbol:
        return None
    return db.scalar(select(Company).where(func.upper(Company.symbol) == symbol.upper()))


def parse_plain_text(content: bytes) -> list[ParsedPage]:
    text = content.decode("utf-8", errors="replace")
    return [ParsedPage(page_number=1, text=text)]


def parse_pdf(content: bytes) -> list[ParsedPage]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF parsing requires optional dependency pypdf. Upload text/Markdown or install pypdf.",
        ) from exc

    import io

    reader = PdfReader(io.BytesIO(content))
    pages: list[ParsedPage] = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append(ParsedPage(page_number=index, text=page.extract_text() or ""))
    return pages


def parse_document_content(filename: str, content: bytes) -> list[ParsedPage]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(content)
    return parse_plain_text(content)


def create_document_from_pages(
    db: Session,
    pages: list[ParsedPage],
    *,
    title: str,
    document_type: str,
    symbol: str | None = None,
    sector: str | None = None,
    fiscal_year: int | None = None,
    quarter: str | None = None,
    source_name: str = "manual",
    source_url: str | None = None,
    local_file_path: str | None = None,
    published_date=None,
) -> Document:
    full_text = "\n\n".join(page.text for page in pages)
    if not full_text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document text is empty")

    normalized_symbol = normalize_symbol(symbol)
    company = find_company(db, normalized_symbol)
    resolved_sector = sector or (company.sector if company else None)
    document = Document(
        company_id=company.id if company else None,
        symbol=normalized_symbol,
        sector=resolved_sector,
        document_type=document_type,
        title=title,
        fiscal_year=fiscal_year,
        quarter=quarter,
        source_name=source_name,
        source_url=source_url,
        local_file_path=local_file_path,
        content_hash=content_hash(full_text),
        published_date=published_date,
        parsed_at=datetime.now(UTC),
        status="parsed",
    )
    db.add(document)
    db.flush()

    chunk_index = 0
    for page in pages:
        page_metadata = {
            "symbol": normalized_symbol,
            "sector": resolved_sector,
            "document_type": document_type,
            "fiscal_year": fiscal_year,
            "quarter": quarter,
        }
        db.add(
            DocumentPage(
                document_id=document.id,
                page_number=page.page_number,
                text=page.text,
                metadata_json=json.dumps(page_metadata),
            )
        )
        for chunk_text, page_number in chunk_page_text(page.text, page.page_number):
            metadata = {
                **page_metadata,
                "title": title,
                "source_name": source_name,
                "source_url": source_url,
                "page_number": page_number,
            }
            chunk = DocumentChunk(
                document_id=document.id,
                company_id=company.id if company else None,
                symbol=normalized_symbol,
                chunk_index=chunk_index,
                chunk_text=chunk_text,
                token_count=len(tokenize(chunk_text)),
                embedding_json=json.dumps(embed_text(chunk_text)),
                metadata_json=json.dumps(metadata),
                source_url=source_url,
                page_number=page_number,
            )
            db.add(chunk)
            db.flush()
            db.add(
                Citation(
                    document_id=document.id,
                    chunk_id=chunk.id,
                    source_name=source_name,
                    source_url=source_url,
                    title=title,
                    page_number=page_number,
                    quote_snippet=first_snippet(chunk_text),
                )
            )
            chunk_index += 1

    db.commit()
    db.refresh(document)
    return document


def ingest_text_document(db: Session, payload: DocumentIngestRequest) -> DocumentResponse:
    document = create_document_from_pages(
        db,
        [ParsedPage(page_number=1, text=payload.text)],
        title=payload.title,
        document_type=payload.document_type,
        symbol=payload.symbol,
        sector=payload.sector,
        fiscal_year=payload.fiscal_year,
        quarter=payload.quarter,
        source_name=payload.source_name,
        source_url=payload.source_url,
        published_date=payload.published_date,
    )
    return serialize_document(document)


async def ingest_upload(
    db: Session,
    file: UploadFile,
    *,
    title: str,
    document_type: str,
    symbol: str | None,
    sector: str | None,
    fiscal_year: int | None,
    quarter: str | None,
    source_name: str,
    source_url: str | None,
    published_date,
) -> DocumentResponse:
    content = await file.read()
    pages = parse_document_content(file.filename or title, content)
    storage_dir = Path("storage/documents")
    storage_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", file.filename or f"{digest}.txt")
    path = storage_dir / f"{digest[:12]}_{safe_name}"
    path.write_bytes(content)
    document = create_document_from_pages(
        db,
        pages,
        title=title,
        document_type=document_type,
        symbol=symbol,
        sector=sector,
        fiscal_year=fiscal_year,
        quarter=quarter,
        source_name=source_name,
        source_url=source_url,
        local_file_path=str(path),
        published_date=published_date,
    )
    return serialize_document(document)


def list_documents(
    db: Session,
    symbol: str | None = None,
    document_type: str | None = None,
    limit: int = 50,
) -> list[DocumentResponse]:
    query = select(Document)
    if symbol:
        query = query.where(func.upper(Document.symbol) == symbol.upper())
    if document_type:
        query = query.where(Document.document_type == document_type)
    rows = db.scalars(query.order_by(Document.created_at.desc()).limit(limit)).all()
    return [serialize_document(row) for row in rows]


def get_document(db: Session, document_id: str) -> DocumentResponse:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return serialize_document(document)


def search_rag(db: Session, payload: RagSearchRequest) -> RagSearchResponse:
    query = (
        select(DocumentChunk, Document, Citation)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(Citation, Citation.chunk_id == DocumentChunk.id)
    )
    if payload.symbols:
        symbols = [symbol.upper() for symbol in payload.symbols]
        query = query.where(func.upper(DocumentChunk.symbol).in_(symbols))
    if payload.sectors:
        query = query.where(Document.sector.in_(payload.sectors))
    if payload.document_types:
        query = query.where(Document.document_type.in_(payload.document_types))
    if payload.date_from:
        query = query.where(Document.published_date >= payload.date_from)
    if payload.date_to:
        query = query.where(Document.published_date <= payload.date_to)

    rows = db.execute(query).all()
    if not rows:
        return RagSearchResponse(chunks=[], citations=[], scores=[])

    query_vector = embed_text(payload.query)
    query_tokens = set(tokenize(payload.query))
    ranked: list[tuple[float, DocumentChunk, Citation]] = []
    for chunk, _document, citation in rows:
        vector = json.loads(chunk.embedding_json)
        vector_score = cosine_similarity(query_vector, vector)
        lexical_score = keyword_score(query_tokens, chunk.chunk_text)
        score = (0.75 * vector_score) + (0.25 * lexical_score)
        if lexical_score > 0 and score > 0:
            ranked.append((score, chunk, citation))

    if not ranked:
        ranked = [
            (keyword_score(query_tokens, chunk.chunk_text), chunk, citation)
            for chunk, _document, citation in rows
            if keyword_score(query_tokens, chunk.chunk_text) > 0
        ]

    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = ranked[: payload.limit]
    chunks: list[RagChunkResponse] = []
    citations: list[CitationResponse] = []
    scores: list[float] = []
    for score, chunk, citation in selected:
        citation_response = serialize_citation(citation)
        citations.append(citation_response)
        scores.append(round(score, 6))
        chunks.append(
            RagChunkResponse(
                id=chunk.id,
                document_id=chunk.document_id,
                symbol=chunk.symbol,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                token_count=chunk.token_count,
                score=round(score, 6),
                source_url=chunk.source_url,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                metadata=json.loads(chunk.metadata_json),
                citation=citation_response,
            )
        )

    return RagSearchResponse(chunks=chunks, citations=citations, scores=scores)
