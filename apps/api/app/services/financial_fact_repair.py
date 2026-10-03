"""Apply an explicitly reviewed, bounded fact repair without rerunning ingestion."""

import hashlib
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.workstation import FinancialFact
from app.providers.fundamentals.extraction import FINANCIAL_EXTRACTION_VERSION


FACT_FIELDS = tuple(column.name for column in FinancialFact.__table__.columns)
DATE_FIELDS = {"period_start", "period_end", "filing_date"}
DECIMAL_FIELDS = {"value", "confidence"}


def fact_snapshot(row: FinancialFact) -> dict:
    return {key: str(value) if isinstance(value := getattr(row, key), (date, Decimal)) else value
            for key in FACT_FIELDS}


def snapshot_hash(snapshot: dict) -> str:
    normalized = dict(snapshot)
    for key in DECIMAL_FIELDS:
        if normalized.get(key) is not None:
            normalized[key] = str(Decimal(normalized[key]).normalize())
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _values(snapshot: dict) -> dict:
    result = dict(snapshot)
    for key in DATE_FIELDS:
        if result.get(key) is not None:
            result[key] = date.fromisoformat(result[key])
    for key in DECIMAL_FIELDS:
        if result.get(key) is not None:
            result[key] = Decimal(result[key])
    return result


def apply_reviewed_repair(db: Session, manifest: dict) -> dict:
    """Validate every before-image before mutation; caller owns commit/rollback.

    Original numeric rows are retained for audit with confidence zero. This
    must run with the matching confidence-filtering readers, never old code.
    Repeating the same repair is a no-op; source or row drift aborts it.
    """
    repair_id = manifest["repair_id"]
    if manifest["extraction_version"] != FINANCIAL_EXTRACTION_VERSION:
        raise ValueError("Repair manifest does not match the installed extractor")
    documents = manifest["documents"]
    ids = [item["document_id"] for item in documents]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Repair requires distinct, explicitly reviewed documents")
    rows = list(db.scalars(select(FinancialFact).where(FinancialFact.document_id.in_(ids)).with_for_update()))
    by_id = {row.id: row for row in rows}
    expected_ids = {old["id"] for item in documents for old in item["before"]}
    completed = [json.loads(by_id[key].diagnostics_json).get("repair", {}).get("id") == repair_id
                 for key in expected_ids if key in by_id]
    if len(completed) == len(expected_ids) and completed and all(completed):
        expected_new = {fact["id"] for item in documents for fact in item["replacements"]}
        if not expected_new.issubset(by_id):
            raise ValueError("Incomplete previous repair requires manual review")
        return {"already_applied": True, "rejected": 0, "inserted": 0}
    if any(completed):
        raise ValueError("Partially applied repair requires manual review")
    for item in documents:
        doc = db.get(Document, item["document_id"])
        if not doc or doc.content_hash != item["content_hash"]:
            raise ValueError("Reviewed document source changed")
        current_ids = {row.id for row in rows if row.document_id == doc.id}
        if current_ids != {old["id"] for old in item["before"]}:
            raise ValueError("Financial fact set changed after review")
        for old in item["before"]:
            row = by_id[old["id"]]
            if (snapshot_hash(fact_snapshot(row)) != old["snapshot_hash"] if "snapshot_hash" in old
                else any(getattr(row, key) != value for key, value in _values(old).items())):
                raise ValueError(f"Financial fact changed after review: {row.id}")
        for fact in item["replacements"]:
            if fact["document_id"] != doc.id or fact["instrument_id"] != item["instrument_id"]:
                raise ValueError("Replacement lies outside reviewed document/instrument")
            if fact["id"] in by_id or Decimal(fact["confidence"]) <= 0 or not fact["source_label"] or not fact["page_number"]:
                raise ValueError("Replacement needs distinct ID and reviewed source provenance")
    inserted = 0
    for item in documents:
        for old in item["before"]:
            row = by_id[old["id"]]
            metadata = json.loads(row.diagnostics_json)
            metadata["repair"] = {"id": repair_id, "status": "rejected_or_superseded",
                                  "original_confidence": str(row.confidence) if row.confidence is not None else None, "reason": item["reason"]}
            row.confidence = Decimal(0)
            row.diagnostics_json = json.dumps(metadata, sort_keys=True)
        for fact in item["replacements"]:
            db.add(FinancialFact(**_values(fact)))
            inserted += 1
    db.flush()
    return {"already_applied": False, "rejected": len(expected_ids), "inserted": inserted}
