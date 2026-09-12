"""Ownership-checked document discovery and complete stored evidence reads."""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select

from app.core.config import settings
from app.domain.retrieval import cosine_similarity, lexical_score, tokenize
from app.models.document import Citation, Document, DocumentChunk, DocumentPage
from app.models.portfolio import Portfolio
from app.models.workstation import SourceArtifact
from app.services.rag_service import embed_text
from app.tools.registry import ToolDefinition, ToolRegistry, tool_result


def _visible(user):
    owned_portfolios = select(Portfolio.id).where(Portfolio.user_id == user.id)
    return or_(
        (Document.visibility == "public") & Document.portfolio_id.is_(None),
        Document.owner_user_id == user.id,
        Document.portfolio_id.in_(owned_portfolios),
    )


def _document(db, user, document_id: str) -> Document | None:
    return db.scalar(select(Document).where(Document.id == document_id, _visible(user)))


def _citation(row: Citation) -> dict:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "chunk_id": row.chunk_id,
        "source_name": row.source_name,
        "source_url": row.source_url,
        "title": row.title,
        "page_number": row.page_number,
        "quote_snippet": row.quote_snippet,
    }


def _citations(
    db,
    document_id: str,
    pages: set[int] | None = None,
    chunk_ids: set[str] | None = None,
) -> list[dict]:
    statement = select(Citation).where(Citation.document_id == document_id)
    if pages is not None:
        statement = statement.where(Citation.page_number.in_(pages))
    if chunk_ids is not None:
        statement = statement.where(Citation.chunk_id.in_(chunk_ids))
    rows = db.scalars(statement.order_by(Citation.page_number, Citation.id)).all()
    return [_citation(row) for row in rows]


class DocumentDiscoveryInput(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    symbols: list[str] | None = Field(default=None, max_length=20)
    document_types: list[str] | None = Field(default=None, max_length=20)
    portfolio_id: str | None = None
    cursor: str | None = Field(default=None, pattern=r"^[0-9]+$")
    limit: int = Field(default=5, ge=1, le=10)


class DocumentReadInput(BaseModel):
    document_id: str
    mode: Literal["pages", "chunks"]
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    chunk_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.mode == "pages":
            if self.page_start is None or self.page_end is None:
                raise ValueError("page_start and page_end are required for page reads")
            if self.page_end < self.page_start:
                raise ValueError("page_end must be greater than or equal to page_start")
            if self.chunk_ids:
                raise ValueError("chunk_ids cannot be combined with page reads")
        elif not self.chunk_ids or self.page_start is not None or self.page_end is not None:
            raise ValueError("chunk_ids alone are required for chunk reads")
        return self


class DocumentNavigationInput(BaseModel):
    document_id: str


class PageImagesInput(BaseModel):
    document_id: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_range(self):
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        if self.page_end - self.page_start >= 4:
            raise ValueError("at most four page images may be requested at once")
        return self


def _discover(db, user, payload: DocumentDiscoveryInput):
    if payload.portfolio_id:
        owned = db.scalar(
            select(Portfolio.id).where(
                Portfolio.id == payload.portfolio_id, Portfolio.user_id == user.id
            )
        )
        if owned is None:
            return tool_result("missing", error={"code": "portfolio_not_found"})
    statement = (
        select(DocumentChunk, Document, Citation)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(Citation, Citation.chunk_id == DocumentChunk.id)
        .where(_visible(user), Document.data_status != "synthetic_demo")
    )
    if payload.symbols:
        statement = statement.where(
            func.upper(Document.symbol).in_([item.upper() for item in payload.symbols])
        )
    if payload.document_types:
        statement = statement.where(Document.document_type.in_(payload.document_types))
    if payload.portfolio_id:
        statement = statement.where(
            or_(Document.portfolio_id == payload.portfolio_id, Document.portfolio_id.is_(None))
        )
    query_tokens = tokenize(payload.query)
    query_vector = embed_text(payload.query)
    grouped: dict[str, dict] = {}
    for chunk, document, citation in db.execute(statement):
        score = lexical_score(
            query_tokens,
            " ".join(
                part for part in (document.title, chunk.section_title, chunk.chunk_text) if part
            ),
        )
        try:
            semantic = cosine_similarity(query_vector, json.loads(chunk.embedding_json))
        except (TypeError, ValueError, json.JSONDecodeError):
            semantic = -1.0
        if score <= 0 and semantic < settings.retrieval_min_semantic_score:
            continue
        combined_score = score + max(0.0, semantic)
        item = grouped.setdefault(
            document.id,
            {
                "document": document,
                "score": combined_score,
                "matches": [],
                "sources": [],
            },
        )
        item["score"] = max(item["score"], combined_score)
        if len(item["matches"]) < 3:
            item["matches"].append(
                {
                    "chunk_id": chunk.id,
                    "page_number": chunk.page_number,
                    "section_title": chunk.section_title,
                    "snippet": " ".join(chunk.chunk_text.split())[:320],
                }
            )
            item["sources"].append(_citation(citation))
    ranked = sorted(grouped.values(), key=lambda item: (-item["score"], item["document"].id))
    offset = int(payload.cursor or 0)
    selected = ranked[offset : offset + payload.limit]
    rows = []
    sources = []
    for item in selected:
        document = item["document"]
        rows.append(
            {
                "document_id": document.id,
                "title": document.title,
                "document_type": document.document_type,
                "symbol": document.symbol,
                "sector": document.sector,
                "fiscal_year": document.fiscal_year,
                "quarter": document.quarter,
                "published_date": str(document.published_date) if document.published_date else None,
                "visibility": document.visibility,
                "extraction_version": document.extraction_version,
                "page_count": db.scalar(
                    select(func.count())
                    .select_from(DocumentPage)
                    .where(DocumentPage.document_id == document.id)
                ),
                "matches": item["matches"],
            }
        )
        sources.extend(item["sources"])
    remaining = max(0, len(ranked) - offset - len(selected))
    return tool_result(
        "ok" if rows else "missing",
        {"documents": rows},
        sources=sources,
        returned=len(rows),
        remaining=remaining,
        continuation=str(offset + len(rows)) if remaining else None,
    )


def _read(db, user, payload: DocumentReadInput):
    document = _document(db, user, payload.document_id)
    if document is None:
        return tool_result("missing", error={"code": "document_not_found"})
    if payload.mode == "pages":
        rows = db.scalars(
            select(DocumentPage)
            .where(
                DocumentPage.document_id == document.id,
                DocumentPage.page_number.between(payload.page_start, payload.page_end),
            )
            .order_by(DocumentPage.page_number)
        ).all()
        requested = set(range(payload.page_start, payload.page_end + 1))
        returned_pages = {row.page_number for row in rows}
        data = {
            "document_id": document.id,
            "extraction_version": document.extraction_version,
            "mode": "pages",
            "pages": [
                {"page_id": row.id, "page_number": row.page_number, "text": row.text}
                for row in rows
            ],
            "extraction_gaps": sorted(requested - returned_pages),
        }
        return tool_result(
            "ok" if rows else "missing",
            data,
            sources=_citations(db, document.id, returned_pages),
            returned=len(rows),
            remaining=len(requested - returned_pages),
        )
    rows = db.scalars(
        select(DocumentChunk)
        .where(
            DocumentChunk.document_id == document.id,
            DocumentChunk.id.in_(payload.chunk_ids),
        )
        .order_by(DocumentChunk.chunk_index)
    ).all()
    returned_ids = {row.id for row in rows}
    return tool_result(
        "ok" if rows else "missing",
        {
            "document_id": document.id,
            "extraction_version": document.extraction_version,
            "mode": "chunks",
            "chunks": [
                {
                    "chunk_id": row.id,
                    "chunk_index": row.chunk_index,
                    "page_number": row.page_number,
                    "section_title": row.section_title,
                    "text": row.chunk_text,
                }
                for row in rows
            ],
            "missing_chunk_ids": sorted(set(payload.chunk_ids) - returned_ids),
        },
        sources=_citations(db, document.id, chunk_ids=returned_ids),
        returned=len(rows),
        remaining=len(set(payload.chunk_ids) - returned_ids),
    )


def _original_path(db, document: Document) -> Path | None:
    values = [document.local_file_path]
    if document.artifact_id:
        artifact = db.get(SourceArtifact, document.artifact_id)
        values.append(artifact.storage_path if artifact else None)
    for value in values:
        if value:
            path = Path(value)
            if path.is_file() and path.suffix.lower() == ".pdf":
                return path
    return None


def _flatten_bookmarks(items, output):
    for item in items:
        if isinstance(item, list):
            _flatten_bookmarks(item, output)
        elif hasattr(item, "title"):
            output.append(item)


def _navigate(db, user, payload: DocumentNavigationInput):
    document = _document(db, user, payload.document_id)
    if document is None:
        return tool_result("missing", error={"code": "document_not_found"})
    stored_pages = db.scalars(
        select(DocumentPage.page_number)
        .where(DocumentPage.document_id == document.id)
        .order_by(DocumentPage.page_number)
    ).all()
    path = _original_path(db, document)
    bookmarks = []
    original_status = "original_unavailable"
    if path is not None:
        try:
            from pypdf import PdfReader

            reader = PdfReader(path)
            flat = []
            _flatten_bookmarks(reader.outline, flat)
            for item in flat:
                try:
                    bookmarks.append(
                        {
                            "title": str(item.title),
                            "page_number": reader.get_destination_page_number(item) + 1,
                            "precision": "page_navigation",
                        }
                    )
                except Exception:
                    continue
            original_status = "available"
        except Exception:
            original_status = "original_unavailable"
    return tool_result(
        "ok",
        {
            "document_id": document.id,
            "stored_page_count": len(stored_pages),
            "stored_page_numbers": stored_pages,
            "bookmarks": bookmarks,
            "bookmark_precision": "page_navigation_not_exact_section_boundaries",
            "original_status": original_status,
        },
        sources=_citations(db, document.id),
        returned=len(bookmarks),
        remaining=0,
    )


def _page_images(db, user, payload: PageImagesInput):
    document = _document(db, user, payload.document_id)
    if document is None:
        return tool_result("missing", error={"code": "document_not_found"})
    path = _original_path(db, document)
    if path is None:
        return tool_result("unavailable", error={"code": "original_unavailable"})
    with tempfile.TemporaryDirectory(prefix="phase8-pages-") as directory:
        prefix = Path(directory) / "page"
        try:
            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-r",
                    "120",
                    "-f",
                    str(payload.page_start),
                    "-l",
                    str(payload.page_end),
                    str(path),
                    str(prefix),
                ],
                check=True,
                capture_output=True,
                timeout=20,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return tool_result("unavailable", error={"code": "page_render_unavailable"})
        files = sorted(Path(directory).glob("page-*.png"))
        images = [
            {
                "page_number": payload.page_start + index,
                "mime_type": "image/png",
                "base64": base64.b64encode(file.read_bytes()).decode("ascii"),
            }
            for index, file in enumerate(files)
        ]
    return tool_result(
        "ok" if images else "unavailable",
        {"document_id": document.id, "images": images},
        sources=_citations(db, document.id, {item["page_number"] for item in images}),
        returned=len(images),
        remaining=0,
        error=None if images else {"code": "page_render_unavailable"},
    )


def register_document_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            "documents.discover",
            "1.0",
            "Find owned or public stored documents and short matching snippets",
            DocumentDiscoveryInput,
            "research:read",
            True,
            False,
            12,
            "medium",
            _discover,
        )
    )
    registry.register(
        ToolDefinition(
            "documents.read",
            "1.0",
            "Read complete stored physical pages or selected chunks",
            DocumentReadInput,
            "research:read",
            True,
            False,
            10,
            "medium",
            _read,
        )
    )
    registry.register(
        ToolDefinition(
            "documents.navigate",
            "1.0",
            "Return stored page count and actual PDF bookmarks when originals exist",
            DocumentNavigationInput,
            "research:read",
            True,
            False,
            8,
            "low",
            _navigate,
        )
    )
    registry.register(
        ToolDefinition(
            "documents.page_images",
            "1.0",
            "Render retained PDF pages for layout-sensitive evidence",
            PageImagesInput,
            "research:read",
            True,
            False,
            25,
            "medium",
            _page_images,
        )
    )
