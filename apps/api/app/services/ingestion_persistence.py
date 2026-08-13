import json
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.artifact_store import LocalArtifactStore
from app.models.workstation import DataSource, MacroObservation, MacroSeries, SourceArtifact
from app.providers.macro.official_workbooks import MacroObservation as ParsedMacroObservation


def source(db: Session, name: str, source_type: str, base_url: str | None, priority: int, sla: int | None, notes: str) -> DataSource:
    row = db.scalar(select(DataSource).where(DataSource.name == name))
    if row is None:
        row = DataSource(name=name, source_type=source_type, base_url=base_url, priority=priority, freshness_sla_minutes=sla, enabled=True, use_notes=notes)
        db.add(row); db.flush()
    return row


def store_artifact(db: Session, data_source: DataSource, content: bytes, *, url: str, method: str, parser_version: str, content_type: str, effective_at: datetime | None = None) -> SourceArtifact:
    digest = sha256(content).hexdigest(); existing = db.scalar(select(SourceArtifact).where(SourceArtifact.sha256 == digest))
    if existing: return existing
    suffix = next((value for marker, value in (("pdf", ".pdf"), ("json", ".json"), ("csv", ".csv"), ("excel", ".xlsx")) if marker in content_type.lower()), ".bin")
    stored = LocalArtifactStore(settings.source_artifact_root).put(content, suffix)
    row = SourceArtifact(data_source_id=data_source.id, source_url=url, http_method=method, request_fingerprint=sha256(f"{method}:{url}".encode()).hexdigest(), effective_at=effective_at, sha256=digest, content_type=content_type, storage_path=stored.storage_path, parser_version=parser_version, status="parsed", response_metadata_json=json.dumps({"bytes": len(content)}))
    db.add(row); db.flush(); return row


def persist_macro(db: Session, observations: list[ParsedMacroObservation], data_source: DataSource, artifact: SourceArtifact) -> int:
    count = 0
    for item in observations:
        series = db.scalar(select(MacroSeries).where(MacroSeries.key == item.series_key))
        if series is None:
            is_sbp = item.series_key.startswith("sbp.")
            metadata = {"is_risk_free": item.series_key == "sbp.tbill.3m_yield", "freshness_sla_minutes": 2880 if is_sbp else data_source.freshness_sla_minutes, "observation_source": item.source}
            series = MacroSeries(key=item.series_key, name=item.series_key.replace(".", " ").title(), unit=item.unit, frequency="daily" if is_sbp else "monthly", source_id=data_source.id, metadata_json=json.dumps(metadata)); db.add(series); db.flush()
        existing = db.scalar(select(MacroObservation).where(MacroObservation.series_id == series.id, MacroObservation.effective_date == item.effective_date, MacroObservation.is_selected.is_(True)))
        if existing and float(existing.value) == item.value: continue
        if existing: existing.is_selected = False
        db.add(MacroObservation(series_id=series.id, effective_date=item.effective_date, release_at=datetime.now(UTC), value=item.value, revision=(existing.revision + 1) if existing else 1, artifact_id=artifact.id, is_selected=True)); count += 1
    return count
