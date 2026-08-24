import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.document import Citation, Document, DocumentChunk, DocumentPage
from app.models.market import Company
from app.models.user import User
from app.models.workstation import Instrument, InstrumentAlias
from app.core.config import settings
from app.domain.retrieval import (
    TOKEN_RE,
    build_retrieval_plan,
    canonical_document_type,
    classify_chunk_content,
    content_adjustment,
    cosine_similarity,
    freshness_adjustment,
    has_table_intent,
    lexical_score,
    reciprocal_rank_fusion,
    source_adjustment,
    source_tier,
    tokenize,
)
from app.schemas.rag import (
    CitationResponse,
    DocumentIngestRequest,
    DocumentResponse,
    RagChunkResponse,
    RagSearchRequest,
    RagDisambiguation,
    RagSearchAudit,
    RagSearchResponse,
)

EMBEDDING_DIMENSIONS = settings.embedding_dimensions
CHUNK_TOKENS = 180
CHUNK_OVERLAP = 40


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    text: str


def normalize_symbol(symbol: str | None) -> str | None:
    return symbol.upper() if symbol else None


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_embedding(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        vector[bucket] += 1.0
    magnitude = math.sqrt(sum(value * value for value in vector))
    if not magnitude:
        return vector
    return [value / magnitude for value in vector]


@lru_cache(maxsize=1)
def _semantic_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is required when EMBEDDING_BACKEND=sentence_transformers"
        ) from exc
    model = SentenceTransformer(settings.embedding_model_name)
    dimension = model.get_embedding_dimension()
    if dimension != EMBEDDING_DIMENSIONS:
        raise RuntimeError(f"Embedding model dimension {dimension} does not match configured {EMBEDDING_DIMENSIONS}")
    return model


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if settings.embedding_backend == "sentence_transformers":
        vectors = _semantic_model().encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return [[float(value) for value in vector.tolist()] for vector in vectors]
    return [_hash_embedding(text) for text in texts]


def active_embedding_model() -> str:
    return (
        settings.embedding_model_name
        if settings.embedding_backend == "sentence_transformers"
        else "token-hash-v1-test-only"
    )


def chunk_page_text(text: str, page_number: int) -> list[tuple[str, int]]:
    """Preserve natural document blocks and split only oversized sections."""

    units: list[str] = []
    paragraph: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if paragraph:
                units.append("\n".join(paragraph))
                paragraph = []
            continue
        is_heading = len(line) <= 120 and (line.isupper() or line.endswith(":") or line.startswith("#"))
        if is_heading:
            if paragraph:
                units.append("\n".join(paragraph))
                paragraph = []
            units.append(raw_line.strip())
        else:
            paragraph.append(raw_line.rstrip())
    if paragraph:
        units.append("\n".join(paragraph))
    if not units and text.strip():
        units = [text.strip()]

    def split_oversized(unit: str) -> list[str]:
        matches = list(TOKEN_RE.finditer(unit))
        if len(matches) <= CHUNK_TOKENS:
            return [unit.strip()]
        parts: list[str] = []
        start = 0
        while start < len(matches):
            end = min(start + CHUNK_TOKENS, len(matches))
            parts.append(unit[matches[start].start():matches[end - 1].end()].strip())
            if end == len(matches):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
        return parts

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for unit in units:
        for part in split_oversized(unit):
            part_tokens = len(tokenize(part))
            if current and current_tokens + part_tokens > CHUNK_TOKENS:
                chunks.append("\n\n".join(current).strip())
                current = []
                current_tokens = 0
            current.append(part)
            current_tokens += part_tokens
            if part_tokens >= CHUNK_TOKENS:
                chunks.append("\n\n".join(current).strip())
                current = []
                current_tokens = 0
    if current:
        chunks.append("\n\n".join(current).strip())
    return [(chunk, page_number) for chunk in chunks if chunk]


def infer_section_title(text: str) -> str | None:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first_line and len(first_line) <= 120 and (first_line.isupper() or first_line.endswith(":")):
        return first_line.rstrip(":")
    return None


def first_snippet(text: str, max_chars: int = 260) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 3]}..."


def serialize_document(document: Document) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        visibility=document.visibility,
        portfolio_id=document.portfolio_id,
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
        source_tier=document.source_tier,
        data_status=document.data_status,
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
    owner_user_id: str | None = None,
    visibility: str = "public",
    portfolio_id: str | None = None,
    artifact_id: str | None = None,
    source_tier_value: int | None = None,
    data_status: str | None = None,
    commit: bool = True,
) -> Document:
    full_text = "\n\n".join(page.text for page in pages)
    if not full_text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document text is empty")

    normalized_symbol = normalize_symbol(symbol)
    company = find_company(db, normalized_symbol)
    resolved_sector = sector or (company.sector if company else None)
    canonical_type = canonical_document_type(document_type)
    resolved_status = data_status or (
        "synthetic_demo"
        if canonical_type == "synthetic_demo_facts" or source_name == "Deterministic Demo Seed"
        else "user_upload" if owner_user_id else "observed"
    )
    resolved_tier = source_tier_value or source_tier(source_name, owner_user_id=owner_user_id)
    document = Document(
        company_id=company.id if company else None,
        owner_user_id=owner_user_id,
        portfolio_id=portfolio_id,
        artifact_id=artifact_id,
        visibility=visibility,
        symbol=normalized_symbol,
        sector=resolved_sector,
        document_type=canonical_type,
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
        source_tier=resolved_tier,
        data_status=resolved_status,
        extraction_version="text-pages-v1",
        parser_version="pypdf-v1" if any(page.page_number > 1 for page in pages) else "plain-text-v1",
    )
    db.add(document)
    db.flush()

    chunk_index = 0
    for page in pages:
        page_metadata = {
            "symbol": normalized_symbol,
            "sector": resolved_sector,
            "document_type": canonical_type,
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
                "embedding_backend": settings.embedding_backend,
                "embedding_model": active_embedding_model(),
                "embedding_index_version": settings.embedding_index_version,
                "content_type": classify_chunk_content(chunk_text),
                "source_tier": resolved_tier,
                "data_status": resolved_status,
            }
            vector = embed_text(chunk_text)
            chunk = DocumentChunk(
                document_id=document.id,
                company_id=company.id if company else None,
                symbol=normalized_symbol,
                chunk_index=chunk_index,
                chunk_text=chunk_text,
                token_count=len(tokenize(chunk_text)),
                embedding_json=json.dumps(vector),
                embedding_vector=vector if db.bind and db.bind.dialect.name == "postgresql" else json.dumps(vector),
                metadata_json=json.dumps(metadata),
                source_url=source_url,
                page_number=page_number,
                section_title=infer_section_title(chunk_text),
                content_type=classify_chunk_content(chunk_text),
                embedding_model=active_embedding_model(),
                embedding_index_version=settings.embedding_index_version,
                embedding_status="indexed",
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

    if commit:
        db.commit()
        db.refresh(document)
    else:
        db.flush()
    return document


def ingest_text_document(db: Session, user: User, payload: DocumentIngestRequest) -> DocumentResponse:
    if payload.portfolio_id:
        from app.services.portfolio_service import get_portfolio_or_404
        get_portfolio_or_404(db, user, payload.portfolio_id)
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
        owner_user_id=user.id if payload.visibility == "private" else None,
        visibility=payload.visibility,
        portfolio_id=payload.portfolio_id,
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
    user: User,
    visibility: str = "private",
    portfolio_id: str | None = None,
) -> DocumentResponse:
    if portfolio_id:
        from app.services.portfolio_service import get_portfolio_or_404
        get_portfolio_or_404(db, user, portfolio_id)
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
        owner_user_id=user.id if visibility == "private" else None,
        visibility=visibility,
        portfolio_id=portfolio_id,
    )
    return serialize_document(document)


def list_documents(
    db: Session,
    user: User,
    symbol: str | None = None,
    document_type: str | None = None,
    limit: int = 50,
) -> list[DocumentResponse]:
    query = select(Document).where(or_(Document.visibility == "public", Document.owner_user_id == user.id))
    if symbol:
        query = query.where(func.upper(Document.symbol) == symbol.upper())
    if document_type:
        query = query.where(Document.document_type == canonical_document_type(document_type))
    rows = db.scalars(query.order_by(Document.created_at.desc()).limit(limit)).all()
    return [serialize_document(row) for row in rows]


def get_document(db: Session, user: User, document_id: str) -> DocumentResponse:
    document = db.scalar(select(Document).where(Document.id == document_id, or_(Document.visibility == "public", Document.owner_user_id == user.id)))
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return serialize_document(document)


def _query_symbols(db: Session, query_text: str) -> tuple[list[str], list[str]]:
    """Resolve explicit symbols and unambiguous canonical names without an LLM."""

    instruments = list(db.scalars(select(Instrument).where(Instrument.active_to.is_(None))))
    if not instruments:
        return [], []
    by_id = {item.id: item for item in instruments}
    symbols = {item.symbol.upper() for item in instruments}
    explicit: set[str] = set()
    for pattern in (
        re.compile(r"\$([A-Z][A-Z0-9.-]{1,29})\b"),
        re.compile(r"\bPSX\s*:\s*([A-Z][A-Z0-9.-]{1,29})\b", re.IGNORECASE),
        re.compile(r"\b([A-Z][A-Z0-9.-]{1,29})\.PSX\b", re.IGNORECASE),
    ):
        explicit.update(match.group(1).upper() for match in pattern.finditer(query_text))
    explicit.update(token for token in re.findall(r"\b[A-Z][A-Z0-9.-]{1,9}\b", query_text) if token in symbols)
    if explicit:
        return sorted(explicit & symbols), []

    phrase_symbols: dict[str, set[str]] = defaultdict(set)
    for instrument in instruments:
        normalized = " ".join(tokenize(instrument.name, meaningful=True))
        if len(normalized) >= 4:
            phrase_symbols[normalized].add(instrument.symbol.upper())
    for instrument_id, alias in db.execute(select(InstrumentAlias.instrument_id, InstrumentAlias.alias)):
        instrument = by_id.get(instrument_id)
        normalized = " ".join(tokenize(alias, meaningful=True))
        if instrument and len(normalized) >= 4:
            phrase_symbols[normalized].add(instrument.symbol.upper())

    normalized_query = f" {' '.join(tokenize(query_text, meaningful=True))} "
    resolved: set[str] = set()
    ambiguous: set[str] = set()
    for phrase, matches in phrase_symbols.items():
        if f" {phrase} " not in normalized_query:
            continue
        if len(matches) == 1:
            resolved.update(matches)
        else:
            ambiguous.update(matches)
    return sorted(resolved), sorted(ambiguous)


def _audit_plan(plan) -> dict[str, object]:
    return {
        "query": plan.query,
        "symbols": list(plan.symbols),
        "sectors": list(plan.sectors),
        "document_types": list(plan.document_types),
        "date_from": plan.date_from.isoformat() if plan.date_from else None,
        "date_to": plan.date_to.isoformat() if plan.date_to else None,
        "portfolio_id": plan.portfolio_id,
        "limit": plan.limit,
    }


def _empty_search_response(
    *,
    plan,
    rejected: Counter | None = None,
    status_value: str = "insufficient_evidence",
    disambiguation: RagDisambiguation | None = None,
) -> RagSearchResponse:
    return RagSearchResponse(
        status=status_value,
        chunks=[],
        citations=[],
        scores=[],
        disambiguation=disambiguation,
        audit=RagSearchAudit(
            plan=_audit_plan(plan),
            semantic_candidates=0,
            lexical_candidates=0,
            fused_candidates=0,
            admitted_candidates=0,
            rejected_by_reason=dict(rejected or {}),
            embedding_model=active_embedding_model(),
            rrf_k=settings.retrieval_rrf_k,
        ),
    )


def search_rag(db: Session, user: User | None, payload: RagSearchRequest) -> RagSearchResponse:
    if payload.portfolio_id:
        if user is None:
            raise HTTPException(status_code=401, detail="Portfolio-scoped retrieval requires authentication")
        from app.services.portfolio_service import get_portfolio_or_404
        get_portfolio_or_404(db, user, payload.portfolio_id)
    resolved_symbols: list[str] = []
    ambiguous_symbols: list[str] = []
    if not payload.symbols:
        resolved_symbols, ambiguous_symbols = _query_symbols(db, payload.query)
    plan = build_retrieval_plan(
        query=payload.query,
        symbols=payload.symbols or resolved_symbols,
        sectors=payload.sectors,
        document_types=payload.document_types,
        date_from=payload.date_from,
        date_to=payload.date_to,
        time_horizon=payload.time_horizon,
        portfolio_id=payload.portfolio_id,
        limit=payload.limit,
    )
    if ambiguous_symbols:
        return _empty_search_response(
            plan=plan,
            status_value="needs_disambiguation",
            disambiguation=RagDisambiguation(
                symbols=ambiguous_symbols,
                reason="The query matched an alias shared by multiple securities.",
            ),
        )

    base_query = (
        select(DocumentChunk, Document, Citation)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(Citation, Citation.chunk_id == DocumentChunk.id)
    )
    base_query = base_query.where(
        Document.visibility == "public"
        if user is None
        else or_(Document.visibility == "public", Document.owner_user_id == user.id)
    )
    base_query = base_query.where(
        Document.data_status != "synthetic_demo",
        DocumentChunk.embedding_status == "indexed",
        DocumentChunk.embedding_model == active_embedding_model(),
        DocumentChunk.embedding_index_version == settings.embedding_index_version,
    )
    if plan.symbols:
        base_query = base_query.where(func.upper(DocumentChunk.symbol).in_(plan.symbols))
    if plan.sectors:
        base_query = base_query.where(Document.sector.in_(plan.sectors))
    if plan.document_types:
        base_query = base_query.where(Document.document_type.in_(plan.document_types))
    if plan.date_from:
        base_query = base_query.where(Document.published_date >= plan.date_from)
    if plan.date_to:
        base_query = base_query.where(Document.published_date <= plan.date_to)
    if plan.portfolio_id:
        base_query = base_query.where(or_(Document.portfolio_id == plan.portfolio_id, Document.visibility == "public"))

    query_vector = embed_text(plan.query)
    candidate_depth = max(settings.retrieval_candidate_depth, plan.limit * 8)
    if db.bind and db.bind.dialect.name == "postgresql":
        semantic_rows = db.execute(
            base_query.where(DocumentChunk.embedding_vector.is_not(None))
            .order_by(DocumentChunk.embedding_vector.cosine_distance(query_vector))
            .limit(candidate_depth)
        ).all()
        lexical_document = func.concat_ws(
            " ",
            Document.title,
            func.coalesce(DocumentChunk.section_title, ""),
            DocumentChunk.chunk_text,
        )
        vector = func.to_tsvector("english", lexical_document)
        lexical_query = func.websearch_to_tsquery("english", plan.query)
        lexical_rows = db.execute(
            base_query.where(vector.op("@@")(lexical_query))
            .order_by(func.ts_rank_cd(vector, lexical_query).desc())
            .limit(candidate_depth)
        ).all()
        rows_by_id = {
            row[0].id: row
            for row in [*semantic_rows, *lexical_rows]
        }
        rows = list(rows_by_id.values())
    else:
        rows = db.execute(base_query).all()
    if not rows:
        return _empty_search_response(plan=plan)

    candidates: dict[str, tuple[DocumentChunk, Document, Citation]] = {
        chunk.id: (chunk, document, citation) for chunk, document, citation in rows
    }
    semantic_scores: dict[str, float] = {}
    lexical_scores: dict[str, float] = {}
    rejected: Counter = Counter()
    for chunk_id, (chunk, document, _citation) in candidates.items():
        try:
            stored_vector = json.loads(chunk.embedding_json)
            semantic_scores[chunk_id] = cosine_similarity(query_vector, stored_vector)
        except (TypeError, ValueError, json.JSONDecodeError):
            semantic_scores[chunk_id] = -1.0
            rejected["malformed_embedding"] += 1
        lexical_text = " ".join(
            value for value in (document.title, chunk.section_title, chunk.chunk_text) if value
        )
        lexical_scores[chunk_id] = lexical_score(plan.query_tokens, lexical_text)

    semantic_ranking = (
        sorted(candidates, key=lambda item: (-semantic_scores[item], item))[:candidate_depth]
        if settings.embedding_backend == "sentence_transformers"
        else []
    )
    lexical_ranking = [
        item
        for item in sorted(candidates, key=lambda value: (-lexical_scores[value], value))
        if lexical_scores[item] > 0
    ][:candidate_depth]
    rrf_scores = reciprocal_rank_fusion(
        [semantic_ranking, lexical_ranking], k=settings.retrieval_rrf_k
    )
    table_intent = has_table_intent(plan.query)
    ranked: list[tuple[float, float, float, float, DocumentChunk, Document, Citation]] = []
    for chunk_id, fused_score in rrf_scores.items():
        chunk, document, citation = candidates[chunk_id]
        semantic = semantic_scores[chunk_id]
        lexical = lexical_scores[chunk_id]
        semantic_ok = (
            settings.embedding_backend == "sentence_transformers"
            and semantic >= settings.retrieval_min_semantic_score
            and lexical > 0
        )
        lexical_ok = lexical >= settings.retrieval_min_lexical_score
        if not (semantic_ok or lexical_ok):
            rejected["below_relevance_threshold"] += 1
            continue
        if chunk.content_type == "boilerplate":
            rejected["boilerplate"] += 1
            continue
        citation_eligible = bool(
            citation.source_name.strip()
            and citation.title.strip()
            and citation.quote_snippet
            and (citation.source_url or document.local_file_path)
        )
        if not citation_eligible:
            rejected["missing_citation_provenance"] += 1
            continue
        final_score = (
            fused_score
            + freshness_adjustment(document.published_date)
            + source_adjustment(document.source_tier)
            + content_adjustment(chunk.content_type, table_intent=table_intent)
        )
        ranked.append((final_score, fused_score, semantic, lexical, chunk, document, citation))

    ranked.sort(key=lambda item: (-item[0], item[4].id))
    selected = ranked[: plan.limit]
    chunks: list[RagChunkResponse] = []
    citations: list[CitationResponse] = []
    scores: list[float] = []
    for score, fused_score, semantic, lexical, chunk, document, citation in selected:
        citation_response = serialize_citation(citation)
        citations.append(citation_response)
        scores.append(round(score, 6))
        chunks.append(
            RagChunkResponse(
                id=chunk.id,
                document_id=chunk.document_id,
                symbol=chunk.symbol,
                document_type=document.document_type,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                token_count=chunk.token_count,
                score=round(score, 6),
                semantic_score=round(semantic, 6),
                lexical_score=round(lexical, 6),
                rrf_score=round(fused_score, 6),
                source_url=chunk.source_url,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                metadata=json.loads(chunk.metadata_json),
                citation=citation_response,
                citation_eligible=True,
            )
        )

    return RagSearchResponse(
        status="ok" if chunks else "insufficient_evidence",
        chunks=chunks,
        citations=citations,
        scores=scores,
        audit=RagSearchAudit(
            plan=_audit_plan(plan),
            semantic_candidates=len(semantic_ranking),
            lexical_candidates=len(lexical_ranking),
            fused_candidates=len(rrf_scores),
            admitted_candidates=len(chunks),
            rejected_by_reason=dict(rejected),
            embedding_model=active_embedding_model(),
            rrf_k=settings.retrieval_rrf_k,
        ),
    )
