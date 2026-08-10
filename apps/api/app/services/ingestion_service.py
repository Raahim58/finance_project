import csv
import io
import json
from datetime import UTC, date, datetime
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.artifact_store import LocalArtifactStore
from app.models.workstation import DataSource, IngestionRun, MacroObservation, MacroSeries, SourceArtifact
from app.providers.macro.official_workbooks import MacroObservation as ParsedMacroObservation
from app.providers.macro.official_workbooks import PbsPriceProvider, WorldBankCommodityProvider
from app.services.market_ingestion import run_market_data_cycle


def source(db: Session, name: str, source_type: str, base_url: str | None, priority: int, sla: int | None, notes: str) -> DataSource:
    row = db.scalar(select(DataSource).where(DataSource.name == name))
    if row is None:
        row = DataSource(name=name, source_type=source_type, base_url=base_url, priority=priority, freshness_sla_minutes=sla, enabled=True, use_notes=notes)
        db.add(row); db.flush()
    return row


def store_artifact(db: Session, data_source: DataSource, content: bytes, *, url: str, method: str, parser_version: str, content_type: str, effective_at: datetime | None = None) -> SourceArtifact:
    digest = sha256(content).hexdigest()
    existing = db.scalar(select(SourceArtifact).where(SourceArtifact.sha256 == digest))
    if existing: return existing
    suffix = ".csv" if "csv" in content_type else ".bin"
    stored = LocalArtifactStore(settings.source_artifact_root).put(content, suffix)
    row = SourceArtifact(data_source_id=data_source.id, source_url=url, http_method=method, request_fingerprint=sha256(f"{method}:{url}".encode()).hexdigest(), effective_at=effective_at, sha256=digest, content_type=content_type, storage_path=stored.storage_path, parser_version=parser_version, status="parsed", response_metadata_json=json.dumps({"bytes": len(content)}))
    db.add(row); db.flush(); return row


def persist_macro(db: Session, observations: list[ParsedMacroObservation], data_source: DataSource, artifact: SourceArtifact) -> int:
    count = 0
    for item in observations:
        series = db.scalar(select(MacroSeries).where(MacroSeries.key == item.series_key))
        if series is None:
            series = MacroSeries(key=item.series_key, name=item.series_key.replace(".", " ").title(), unit=item.unit, frequency="monthly", source_id=data_source.id, metadata_json="{}")
            db.add(series); db.flush()
        existing = db.scalar(select(MacroObservation).where(MacroObservation.series_id == series.id, MacroObservation.effective_date == item.effective_date, MacroObservation.is_selected.is_(True)))
        if existing and float(existing.value) == item.value: continue
        if existing: existing.is_selected = False
        revision = (existing.revision + 1) if existing else 1
        db.add(MacroObservation(series_id=series.id, effective_date=item.effective_date, release_at=datetime.now(UTC), value=item.value, revision=revision, artifact_id=artifact.id, is_selected=True)); count += 1
    return count


def import_nccpl_csv(db: Session, content: bytes) -> dict[str, object]:
    data_source = source(db, "NCCPL manual export", "macro", "https://www.nccpl.com.pk/market-information", 30, 1440, "Manual CSV import only; automation remains disabled while the public export contract is blocked.")
    artifact = store_artifact(db, data_source, content, url="manual://nccpl-export", method="UPLOAD", parser_version="nccpl-manual-csv-v1", content_type="text/csv")
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    required = {"date", "category", "value"}
    if not reader.fieldnames or not required.issubset({value.strip().lower() for value in reader.fieldnames}):
        raise HTTPException(status_code=422, detail="NCCPL CSV requires date, category, and value columns")
    parsed = []
    for row in reader:
        normalized = {key.strip().lower(): value for key, value in row.items()}
        try:
            effective = date.fromisoformat(normalized["date"]); value = float(normalized["value"])
        except (ValueError, TypeError):
            continue
        category = normalized["category"].strip().lower().replace(" ", "_")
        parsed.append(ParsedMacroObservation(f"nccpl.flow.{category}", effective, value, normalized.get("unit") or "PKR", "nccpl_manual"))
    accepted = persist_macro(db, parsed, data_source, artifact)
    db.commit()
    return {"artifact_id": artifact.id, "accepted": accepted, "attempted": len(parsed), "source": data_source.name}


def refresh_provider(db: Session, provider: str, run_key: str | None = None):
    normalized = provider.strip().lower()
    key = run_key or date.today().isoformat()
    existing = db.scalar(select(IngestionRun).where(IngestionRun.job_key == f"refresh:{normalized}", IngestionRun.run_key == key))
    if existing: return existing
    run = IngestionRun(job_key=f"refresh:{normalized}", run_key=key, provider=normalized, status="running")
    db.add(run); db.commit(); db.refresh(run)
    try:
        if normalized in {"mock", "dps", "yahoo", "auto", "psxdata"}:
            result = run_market_data_cycle(db, normalized); run.attempted_count = result.records_written; run.accepted_count = result.records_written; run.rejected_count = 0
        elif normalized in {"pbs", "world_bank"}:
            provider_object = PbsPriceProvider() if normalized == "pbs" else WorldBankCommodityProvider()
            observations = provider_object.fetch()
            data_source = source(db, normalized.upper(), "macro", provider_object.workbook_url, 10, 45_000, "Official structured workbook")
            # The provider validates the live workbook; the parsed canonical rows are preserved as a bounded JSON artifact for audit.
            content = json.dumps([{"series_key": row.series_key, "effective_date": row.effective_date.isoformat(), "value": row.value, "unit": row.unit} for row in observations], sort_keys=True).encode()
            artifact = store_artifact(db, data_source, content, url=provider_object.workbook_url, method="GET", parser_version=provider_object.parser_version, content_type="application/json")
            run.attempted_count = len(observations); run.accepted_count = persist_macro(db, observations, data_source, artifact)
        else:
            raise HTTPException(status_code=422, detail="Provider is not enabled for refresh")
        run.status = "completed"; run.finished_at = datetime.now(UTC)
    except Exception as exc:
        run.status = "failed"; run.error_class = type(exc).__name__; run.error_message = str(exc)[:2000]; run.finished_at = datetime.now(UTC); db.commit(); raise
    db.commit(); db.refresh(run); return run


def list_ingestion_runs(db: Session, limit: int = 100):
    return [{"id": row.id, "job_key": row.job_key, "run_key": row.run_key, "provider": row.provider, "status": row.status, "attempted_count": row.attempted_count, "accepted_count": row.accepted_count, "rejected_count": row.rejected_count, "error_class": row.error_class, "error_message": row.error_message, "started_at": row.started_at, "finished_at": row.finished_at} for row in db.scalars(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit))]
