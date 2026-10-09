"""Retained report evidence preparation; never executed by page reads."""

import hashlib
from datetime import date
from fastapi import HTTPException
from sqlalchemy import select, func, or_, case
from app.core.config import settings
from app.models.document import Document, DocumentPage, DocumentChunk
from app.models.workstation import SourceArtifact
from app.ingestion.artifact_store import get_artifact_store
from app.providers.fundamentals.extraction import _native_text_pages
from app.services.rag_service import ParsedPage, index_document_pages, active_embedding_model

REPORT_TYPES = ("annual_report", "quarterly_report", "interim_report")


def selected_reports(db, symbol):
    rows = list(
        db.scalars(
            select(Document)
            .where(
                Document.symbol == symbol,
                Document.visibility == "public",
                Document.status == "parsed",
                Document.data_status == "observed",
                Document.document_type.in_(REPORT_TYPES),
                Document.published_date <= date.today(),
            )
            .order_by(Document.published_date.desc(), Document.id)
        )
    )
    annual = next((r for r in rows if r.document_type == "annual_report"), None)
    interim = next((r for r in rows if r.document_type != "annual_report"), None)
    return [r for r in (annual, interim) if r]


def report_coverage(db, symbol):
    return [
        {
            "document_id": r.id,
            "title": r.title,
            "source_url": r.source_url,
            "source_name": r.source_name,
            "document_type": r.document_type,
            "published_date": r.published_date,
            "artifact_id": r.artifact_id,
            "content_hash": r.content_hash,
            "pages": db.scalar(
                select(func.count())
                .select_from(DocumentPage)
                .where(DocumentPage.document_id == r.id)
            ),
            "chunks": db.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.document_id == r.id)
            ),
            "indexed": index_current(db, r.id),
        }
        for r in selected_reports(db, symbol)
    ]


def index_current(db, document_id):
    total, current = db.execute(
        select(
            func.count(DocumentChunk.id),
            func.count(DocumentChunk.id).filter(
                DocumentChunk.embedding_status == "indexed",
                DocumentChunk.embedding_model == active_embedding_model(),
                DocumentChunk.embedding_index_version == settings.embedding_index_version,
                DocumentChunk.embedding_vector.is_not(None),
            ),
        ).where(DocumentChunk.document_id == document_id)
    ).one()
    pages = db.scalar(
        select(func.count())
        .select_from(DocumentPage)
        .where(DocumentPage.document_id == document_id)
    )
    return bool(total and pages) and total == current


def prepare_report(db, document_id):
    document = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
    if document is None or document.visibility != "public" or document.data_status != "observed":
        raise ValueError("Public observed report not found")
    lexical_ready = settings.pipeline_enabled and bool(db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id==document_id)))
    if index_current(db, document_id) or lexical_ready:
        return {"document_id": document_id, "status": "cached"}
    artifact = db.get(SourceArtifact, document.artifact_id) if document.artifact_id else None
    if not artifact or not artifact.storage_path:
        raise ValueError("Retained report artifact missing")
    content = get_artifact_store(settings).get(artifact.storage_path)
    if hashlib.sha256(content).hexdigest() != artifact.sha256:
        raise ValueError("Artifact hash mismatch")
    pages = [ParsedPage(p.page_number, p.text) for p in _native_text_pages(content)]
    count = index_document_pages(db, document, pages)
    db.commit()
    return {"document_id": document_id, "status": "indexed", "pages": len(pages), "chunks": count}


def document_page(db, user, document_id, page_number):
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            or_(Document.visibility == "public", Document.owner_user_id == user.id),
        )
    )
    if document is None:
        raise HTTPException(404, "Document not found")
    page = db.scalar(
        select(DocumentPage).where(
            DocumentPage.document_id == document_id, DocumentPage.page_number == page_number
        )
    )
    if page is None:
        raise HTTPException(404, "Page text has not been indexed")
    return {
        "document_id": document.id,
        "title": document.title,
        "source_name": document.source_name,
        "source_url": document.source_url,
        "page_number": page.page_number,
        "text": page.text,
    }


def company_windows(db, symbol, limit=12):
    ids = [r.id for r in selected_reports(db, symbol)]
    if not ids:
        return []
    base = select(DocumentChunk).where(
        DocumentChunk.document_id.in_(ids),
        DocumentChunk.content_type.in_(("narrative", "mixed")),
        DocumentChunk.embedding_status == "indexed",
        DocumentChunk.embedding_model == active_embedding_model(),
        DocumentChunk.embedding_index_version == settings.embedding_index_version,
    )
    topics = (
        ("business", "operations", "risk"),
        ("oil", "fuel", "energy"),
        ("interest", "borrow", "floating", "debt"),
        ("exchange", "currency", "export", "import"),
    )
    # Bound text fetched from large reports; interleave topics so one factor cannot
    # crowd every other exposure out of the finite model context.
    buckets = []
    for terms in topics:
        score = sum(
            case((func.lower(DocumentChunk.chunk_text).contains(t), 1), else_=0) for t in terms
        )
        buckets.append(
            list(
                db.scalars(
                    base.order_by(
                        score.desc(),
                        DocumentChunk.document_id,
                        DocumentChunk.page_number,
                        DocumentChunk.chunk_index,
                        DocumentChunk.id,
                    ).limit(32)
                )
            )
        )
    ranked = [bucket[i] for i in range(32) for bucket in buckets if i < len(bucket)]
    # Ensure the latest interim is represented even if the longer annual report
    # dominates keyword scores. These are two additional bounded single-row reads.
    report_windows = []
    for document_id in ids:
        row = db.scalar(
            base.where(DocumentChunk.document_id == document_id)
            .order_by(
                DocumentChunk.page_number,
                DocumentChunk.chunk_index,
                DocumentChunk.id,
            )
            .limit(1)
        )
        if row:
            report_windows.append(row)
    ranked = report_windows + ranked
    selected, seen = [], set()
    for c in ranked:
        if (c.document_id, c.page_number) in seen:
            continue
        seen.add((c.document_id, c.page_number))
        d = db.get(Document, c.document_id)
        selected.append(
            {
                "id": "chunk:" + c.id,
                "document_id": d.id,
                "page_number": c.page_number,
                "title": d.title,
                "source_name": d.source_name,
                "source_url": d.source_url,
                "published_date": str(d.published_date),
                "text": " ".join(c.chunk_text.split())[:1000],
            }
        )
        if len(selected) == limit:
            break
    return selected
