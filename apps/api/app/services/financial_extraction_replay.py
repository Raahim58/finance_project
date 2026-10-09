"""Versioned fact replacement: preserve original rows, promote only parsed source facts."""
from datetime import UTC, datetime
from decimal import Decimal
import json
from sqlalchemy import select
from app.models.workstation import FinancialFact


def save_extracted_facts(db, document, instrument, facts, diagnostics, extraction_version, *, strict):
    old = list(db.scalars(select(FinancialFact).where(FinancialFact.document_id == document.id).with_for_update()))
    next_version = max((row.version for row in old), default=0) + 1
    for row in old:
        if row.confidence is not None and row.confidence <= 0:
            continue
        metadata = json.loads(row.diagnostics_json or "{}")
        metadata["reextraction"] = {
            "status": "superseded", "replacement_extraction_version": extraction_version,
            "source_content_hash": document.content_hash,
            "original_confidence": str(row.confidence) if row.confidence is not None else None,
            "superseded_at": datetime.now(UTC).isoformat(),
        }
        row.confidence = Decimal(0)
        row.diagnostics_json = json.dumps(metadata, sort_keys=True)
    created = []
    for fact in facts:
        row = FinancialFact(
            instrument_id=instrument.id, taxonomy_key=fact.taxonomy_key,
            period_type="instant" if strict and fact.taxonomy_key in {"assets","liabilities","equity","debt"}
                        else "annual" if document.document_type == "annual_report" else "interim",
            period_start=fact.period_start, period_end=fact.period_end, filing_date=document.published_date,
            value=fact.value, unit=fact.unit, currency=fact.currency, consolidated=fact.consolidated,
            document_id=document.id, page_number=fact.page_number, source_label=fact.source_label,
            extraction_method=fact.extraction_method, confidence=fact.confidence, version=next_version,
            diagnostics_json=json.dumps({"messages":diagnostics,"extraction_version":extraction_version,
                                         "source_content_hash":document.content_hash}),
        )
        db.add(row); created.append(row)
    db.flush()
    return created
