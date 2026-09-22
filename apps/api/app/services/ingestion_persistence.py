import json
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.artifact_store import get_artifact_store
from app.models.workstation import DataSource, MacroObservation, MacroSeries, SourceArtifact
from app.providers.macro.official_workbooks import MacroObservation as ParsedMacroObservation


def source(db: Session, name: str, source_type: str, base_url: str | None, priority: int, sla: int | None, notes: str) -> DataSource:
    row = db.scalar(select(DataSource).where(DataSource.name == name))
    if row is None:
        row = DataSource(name=name, source_type=source_type, base_url=base_url, priority=priority, freshness_sla_minutes=sla, enabled=True, use_notes=notes)
        db.add(row); db.flush()
    return row


def store_artifact(db: Session, data_source: DataSource, content: bytes, *, url: str, method: str, parser_version: str, content_type: str, effective_at: datetime | None = None) -> SourceArtifact:
    digest = sha256(content).hexdigest()
    request_fingerprint = sha256(f"{method}:{url}".encode()).hexdigest()
    identity = (
        SourceArtifact.data_source_id == data_source.id,
        SourceArtifact.request_fingerprint == request_fingerprint,
        SourceArtifact.sha256 == digest,
    )
    existing = db.scalar(select(SourceArtifact).where(*identity))
    if existing: return existing
    suffix = next((value for marker, value in (("pdf", ".pdf"), ("json", ".json"), ("csv", ".csv"), ("excel", ".xlsx")) if marker in content_type.lower()), ".bin")
    stored = get_artifact_store(settings).put(content, suffix)
    row = SourceArtifact(data_source_id=data_source.id, source_url=url, http_method=method, request_fingerprint=request_fingerprint, effective_at=effective_at, sha256=digest, content_type=content_type, storage_path=stored.storage_path, parser_version=parser_version, status="parsed", response_metadata_json=json.dumps({"bytes": len(content)}))
    try:
        with db.begin_nested():
            db.add(row); db.flush()
        return row
    except IntegrityError:
        # The same source request/content is idempotent, while identical bytes
        # observed from another source or URL retain independent provenance.
        existing = db.scalar(select(SourceArtifact).where(*identity))
        if existing is None:
            raise
        return existing


def persist_macro(db: Session, observations: list[ParsedMacroObservation], data_source: DataSource, artifact: SourceArtifact) -> int:
    count = 0
    for item in observations:
        series = db.scalar(select(MacroSeries).where(MacroSeries.key == item.series_key))
        if series is None:
            is_sbp = item.series_key.startswith("sbp.")
            metadata = {"is_risk_free": item.series_key == "sbp.tbill.3m_yield", "freshness_sla_minutes": 2880 if is_sbp else data_source.freshness_sla_minutes, "observation_source": item.source}
            series = MacroSeries(key=item.series_key, name=item.series_key.replace(".", " ").title(), unit=item.unit, frequency="daily" if is_sbp else "monthly", source_id=data_source.id, metadata_json=json.dumps(metadata)); db.add(series); db.flush()
        elif series.source_id != data_source.id:
            # Legacy source-specific keys retain their original owner. Canonical
            # multi-provider series use MacroSeriesProvider and reconciliation;
            # never silently rewrite series ownership when a fallback appears.
            metadata = json.loads(series.metadata_json or "{}")
            observed_sources = set(metadata.get("observed_sources", []))
            observed_sources.add(item.source)
            metadata["observed_sources"] = sorted(observed_sources)
            metadata["data_classification"] = "observed"
            series.metadata_json = json.dumps(metadata, sort_keys=True)
        existing = db.scalar(select(MacroObservation).where(MacroObservation.series_id == series.id, MacroObservation.effective_date == item.effective_date, MacroObservation.is_selected.is_(True)))
        if existing and float(existing.value) == item.value: continue
        if existing: existing.is_selected = False
        retrieved_at = datetime.now(UTC)
        db.add(MacroObservation(series_id=series.id, effective_date=item.effective_date, release_at=retrieved_at, value=item.value, revision=(existing.revision + 1) if existing else 1, artifact_id=artifact.id, source_series_id=item.series_key, retrieved_at=retrieved_at, authority="national_official" if item.source in {"sbp", "pbs"} else "official_international", confidence=1 if item.source in {"sbp", "pbs"} else 0.95, selection_reason='{"policy":"legacy_single_source"}', is_selected=True)); count += 1
    return count
