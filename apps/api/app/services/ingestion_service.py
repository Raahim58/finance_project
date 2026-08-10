import csv
import io
import json
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingestion.artifact_store import LocalArtifactStore
from app.models.document import Document
from app.models.workstation import (
    DataSource,
    Event,
    EventEntityLink,
    EventSource,
    IngestionRun,
    Instrument,
    MacroObservation,
    MacroSeries,
    SourceArtifact,
)
from app.providers.macro.official_workbooks import MacroObservation as ParsedMacroObservation
from app.providers.macro.official_workbooks import PbsPriceProvider, WorldBankCommodityProvider
from app.services.market_ingestion import run_market_data_cycle
from app.services.market_ingestion import persist_market_data
from app.services.market_providers import get_market_data_provider
from app.services.canonical_market_service import price_series
from app.services.trading_calendar_service import sessions_between


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
            metadata = {
                "is_risk_free": item.series_key == "sbp.tbill.3m_yield",
                "freshness_sla_minutes": 2880 if is_sbp else data_source.freshness_sla_minutes,
                "observation_source": item.source,
            }
            series = MacroSeries(key=item.series_key, name=item.series_key.replace(".", " ").title(), unit=item.unit, frequency="daily" if is_sbp else "monthly", source_id=data_source.id, metadata_json=json.dumps(metadata))
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
    if existing and existing.status in {"running", "completed"}:
        return existing
    if existing:
        run = existing
        run.status = "running"; run.retry_count += 1; run.error_class = None; run.error_message = None
        run.started_at = datetime.now(UTC); run.finished_at = None
        run.attempted_count = run.accepted_count = run.rejected_count = 0
    else:
        run = IngestionRun(job_key=f"refresh:{normalized}", run_key=key, provider=normalized, status="running")
        db.add(run)
    db.commit(); db.refresh(run)
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
        elif normalized == "sbp":
            from app.providers.macro.sbp import SbpKeyIndicatorsProvider
            provider_object = SbpKeyIndicatorsProvider()
            content, observations = provider_object.fetch()
            data_source = source(db, "SBP", "macro", provider_object.page_url, 10, 2880, "Official SBP observed key indicators; raw HTML is retained for audit.")
            artifact = store_artifact(db, data_source, content, url=provider_object.page_url, method="GET", parser_version=provider_object.parser_version, content_type="text/html")
            run.attempted_count = len(observations); run.accepted_count = persist_macro(db, observations, data_source, artifact)
        elif normalized == "scstrade":
            result = _refresh_scstrade(db)
            run.attempted_count = result["attempted"]; run.accepted_count = result["accepted"]; run.rejected_count = result["rejected"]
        elif normalized == "psx_financials":
            result = _refresh_psx_financials(db)
            run.attempted_count = result["attempted"]; run.accepted_count = result["accepted"]; run.rejected_count = result["rejected"]
        elif normalized == "mettis":
            result = _refresh_mettis(db)
            run.attempted_count = result["attempted"]; run.accepted_count = result["accepted"]; run.rejected_count = result["rejected"]
        else:
            raise HTTPException(status_code=422, detail="Provider is not enabled for refresh")
        run.status = "completed"; run.finished_at = datetime.now(UTC)
    except Exception as exc:
        run_id = run.id
        db.rollback()
        run = db.get(IngestionRun, run_id)
        run.status = "failed"; run.error_class = type(exc).__name__; run.error_message = str(exc)[:2000]; run.finished_at = datetime.now(UTC); db.commit(); raise
    db.commit(); db.refresh(run); return run


def _refresh_scstrade(db: Session) -> dict[str, int]:
    from app.providers.market.scstrade import ScsTradeProvider
    from app.services.market_providers import LatestPriceRow

    provider = ScsTradeProvider()
    end = date.today(); start = end - timedelta(days=120)
    attempted = accepted = rejected = 0
    for symbol in settings.market_data_default_symbols:
        try:
            rows = provider.fetch_history(symbol, start, end)
        except Exception:
            rejected += 1
            continue
        attempted += len(rows)
        normalized = []
        for index, row in enumerate(rows):
            previous = rows[index - 1].close if index else row.close - row.change
            if previous <= 0:
                rejected += 1
                continue
            normalized.append(LatestPriceRow(symbol=symbol, trade_date=row.trade_date, close=row.close, previous_close=previous, open=row.open, high=row.high, low=row.low, volume=row.volume, source_url=provider.endpoint))
        if normalized:
            result = persist_market_data(db, latest_prices=normalized, source="scstrade")
            accepted += int(result["canonical_observations"]); rejected += int(result["rejected"])
    return {"attempted": attempted, "accepted": accepted, "rejected": rejected}


def _report_document_type(report_type: str) -> tuple[str, str | None]:
    lowered = report_type.lower()
    if "annual" in lowered:
        return "annual_report", None
    if "quarter" in lowered or "qtr" in lowered:
        return "quarterly_report", None
    if "half" in lowered:
        return "half_year_report", None
    return "company_report", None


def _refresh_psx_financials(db: Session, symbols: list[str] | None = None, limit: int | None = None) -> dict[str, int]:
    from app.providers.fundamentals.psx_financials import PsxFinancialsProvider
    from app.services.rag_service import create_document_from_pages, parse_pdf

    provider = PsxFinancialsProvider()
    data_source = source(db, "PSX Financials", "company_reports", provider.base_url, 10, 1440, "Official PSX company-report catalogue and PDFs; newly observed reports are indexed into RAG.")
    attempted = accepted = rejected = 0
    remaining = limit if limit is not None else settings.research_report_limit_per_run
    for symbol in (symbols or settings.market_data_default_symbols):
        if remaining <= 0:
            break
        try:
            catalog = provider.fetch_company_catalog(symbol)
        except Exception:
            rejected += 1
            continue
        for item in sorted(catalog, key=lambda value: value.posting_date, reverse=True):
            if remaining <= 0:
                break
            attempted += 1
            if db.scalar(select(Document.id).where(Document.source_url == item.report_url)):
                continue
            try:
                content = provider.fetch_report(item)
                artifact = store_artifact(db, data_source, content, url=item.report_url, method="GET", parser_version=provider.parser_version, content_type="application/pdf", effective_at=datetime.combine(item.posting_date, datetime.min.time(), tzinfo=UTC))
                pages = parse_pdf(content)
                document_type, quarter = _report_document_type(item.report_type)
                year_match = next((token for token in item.period_ended.replace("/", "-").split("-") if token.isdigit() and len(token) == 4), None)
                create_document_from_pages(db, pages, title=f"{symbol} {item.report_type} — {item.period_ended}", document_type=document_type, symbol=symbol, fiscal_year=int(year_match) if year_match else None, quarter=quarter, source_name="PSX Financials", source_url=item.report_url, published_date=item.posting_date, visibility="public", artifact_id=artifact.id, commit=False)
                db.commit()
                accepted += 1; remaining -= 1
            except Exception:
                db.rollback()
                data_source = source(db, "PSX Financials", "company_reports", provider.base_url, 10, 1440, "Official PSX company-report catalogue and PDFs; newly observed reports are indexed into RAG.")
                rejected += 1
    return {"attempted": attempted, "accepted": accepted, "rejected": rejected}


def refresh_company_research(db: Session, instrument_id: str, limit: int = 5) -> dict[str, object]:
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    key = f"{instrument.symbol}:{date.today().isoformat()}"
    existing = db.scalar(select(IngestionRun).where(IngestionRun.job_key == "company-research-refresh", IngestionRun.run_key == key))
    if existing and existing.status == "completed":
        return {"run_id": existing.id, "symbol": instrument.symbol, "status": existing.status, "attempted": existing.attempted_count, "accepted": existing.accepted_count, "rejected": existing.rejected_count, "idempotent_reuse": True}
    run = existing or IngestionRun(job_key="company-research-refresh", run_key=key, provider="psx_financials", status="running")
    if existing:
        run.status = "running"; run.retry_count += 1; run.error_class = None; run.error_message = None; run.finished_at = None
    else:
        db.add(run)
    db.commit(); db.refresh(run)
    try:
        result = _refresh_psx_financials(db, [instrument.symbol], limit)
        run = db.get(IngestionRun, run.id)
        run.attempted_count = result["attempted"]; run.accepted_count = result["accepted"]; run.rejected_count = result["rejected"]
        run.status = "completed"; run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback(); run = db.get(IngestionRun, run.id)
        run.status = "failed"; run.error_class = type(exc).__name__; run.error_message = str(exc)[:2000]; run.finished_at = datetime.now(UTC); db.commit()
    return {"run_id": run.id, "symbol": instrument.symbol, "status": run.status, "attempted": run.attempted_count, "accepted": run.accepted_count, "rejected": run.rejected_count, "idempotent_reuse": False}


def _refresh_mettis(db: Session) -> dict[str, int]:
    from decimal import Decimal
    from app.providers.news.mettis import MettisProvider
    from app.services.rag_service import ParsedPage, create_document_from_pages

    provider = MettisProvider()
    articles = provider.fetch_listing()
    data_source = source(db, "Mettis Global", "news_metadata", provider.listing_url, 50, 240, "Headline, timestamp and visible-summary metadata only; article bodies are not republished.")
    content = json.dumps([{"title": item.title, "url": item.url, "summary": item.summary} for item in articles], sort_keys=True).encode()
    artifact = store_artifact(db, data_source, content, url=provider.listing_url, method="GET", parser_version=provider.parser_version, content_type="application/json")
    instruments = list(db.scalars(select(Instrument)))
    attempted = len(articles); accepted = rejected = 0
    for listed in articles:
        if db.scalar(select(EventSource.id).where(EventSource.source_url == listed.url)):
            continue
        try:
            article = provider.fetch_article_metadata(listed.url)
            text = article.summary or listed.summary
            document = None
            if text:
                document = create_document_from_pages(db, [ParsedPage(1, text)], title=article.title or listed.title, document_type="news_summary", source_name="Mettis Global", source_url=listed.url, published_date=article.published_at.date() if article.published_at else None, visibility="public", artifact_id=artifact.id, commit=False)
            occurred_at = article.published_at or datetime.now(UTC)
            event = Event(event_type="news", title=(article.title or listed.title)[:255], occurred_at=occurred_at, confidence=Decimal("0.750000"), details_json=json.dumps({"summary": text, "author": article.author, "timestamp_observed": article.published_at is not None}))
            db.add(event); db.flush()
            db.add(EventSource(event_id=event.id, source_url=listed.url, source_name="Mettis Global", artifact_id=artifact.id, document_id=document.id if document else None))
            searchable = f"{article.title or listed.title} {text or ''}".upper()
            for instrument in instruments:
                if instrument.symbol.upper() in searchable.split():
                    db.add(EventEntityLink(event_id=event.id, entity_type="instrument", entity_key=instrument.symbol, link_method="exact_symbol_token", confidence=Decimal("1.000000")))
            db.commit(); accepted += 1
        except Exception:
            db.rollback(); rejected += 1
    return {"attempted": attempted, "accepted": accepted, "rejected": rejected}


def run_due_ingestion_jobs(db: Session) -> list[dict[str, object]]:
    """Run source-specific schedules using idempotent period keys."""
    if not settings.scheduled_research_enabled or settings.market_data_mode == "mock":
        return []
    today = date.today()
    schedules = [
        ("mettis", today.isoformat()),
        ("psx_financials", today.isoformat()),
        ("sbp", today.isoformat()),
        ("scstrade", f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"),
        ("pbs", f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"),
        ("world_bank", f"{today.year}-{today.month:02d}"),
    ]
    results = []
    for provider, key in schedules:
        try:
            run = refresh_provider(db, provider, key)
            results.append({"provider": provider, "status": run.status, "run_id": run.id})
        except Exception as exc:
            db.rollback()
            results.append({"provider": provider, "status": "failed", "error_class": type(exc).__name__})
    return results


def list_ingestion_runs(db: Session, limit: int = 100):
    return [{"id": row.id, "job_key": row.job_key, "run_key": row.run_key, "provider": row.provider, "status": row.status, "attempted_count": row.attempted_count, "accepted_count": row.accepted_count, "rejected_count": row.rejected_count, "error_class": row.error_class, "error_message": row.error_message, "started_at": row.started_at, "finished_at": row.finished_at} for row in db.scalars(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit))]


def historical_gaps(db: Session, symbol: str, start: date, end: date) -> dict[str, object]:
    observed = {row.trade_date for row in price_series(db, symbol, start, end)}
    expected = sessions_between(db, start, end)
    gaps = [row.session_date for row in expected if row.session_date not in observed]
    return {
        "symbol": symbol.upper(),
        "start": start,
        "end": end,
        "observed_sessions": len(observed),
        "expected_sessions": len(expected),
        "missing_sessions": gaps,
        "assumed_calendar_sessions": sum(row.status == "assumed_weekday" for row in expected),
    }


def run_historical_backfill(
    db: Session,
    *,
    provider_name: str,
    symbols: list[str],
    start: date,
    end: date,
    run_key: str | None = None,
) -> IngestionRun:
    normalized_provider = provider_name.strip().lower()
    normalized_symbols = sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})
    if normalized_provider not in {"dps", "yahoo", "psxdata", "auto"}:
        raise HTTPException(status_code=422, detail="Historical backfill provider must be dps, yahoo, psxdata, or auto")
    if not normalized_symbols:
        raise HTTPException(status_code=422, detail="At least one symbol is required")
    key = run_key or sha256(f"{normalized_provider}:{','.join(normalized_symbols)}:{start}:{end}".encode()).hexdigest()[:32]
    job_key = "market-history-backfill"
    existing = db.scalar(select(IngestionRun).where(IngestionRun.job_key == job_key, IngestionRun.run_key == key))
    if existing:
        if existing.status in {"completed", "running"}:
            return existing
        # A stable job key must remain idempotent after success, but a failed run
        # must be retryable. Reuse the audit row and retain the retry count.
        existing.status = "running"
        existing.retry_count += 1
        existing.error_class = None
        existing.error_message = None
        existing.started_at = datetime.now(UTC)
        existing.finished_at = None
        existing.attempted_count = 0
        existing.accepted_count = 0
        existing.rejected_count = 0
        db.commit()
        run = existing
    else:
        run = IngestionRun(job_key=job_key, run_key=key, provider=normalized_provider, status="running")
        db.add(run)
        db.commit()
        db.refresh(run)
    try:
        provider = get_market_data_provider(normalized_provider)
        attempted = accepted = rejected = 0
        for symbol in normalized_symbols:
            rows = provider.fetch_symbol_history(symbol, start, end)
            attempted += len(rows)
            if not rows:
                rejected += 1
                continue
            actual_source = "dps" if any("dps.psx.com.pk" in (row.source_url or "") for row in rows) else ("yahoo" if normalized_provider == "auto" else normalized_provider)
            result = persist_market_data(db, latest_prices=rows, source=actual_source)
            accepted += int(result.get("canonical_observations", 0))
            rejected += int(result.get("rejected", 0))
        run.attempted_count = attempted
        run.accepted_count = accepted
        run.rejected_count = rejected
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
    except Exception as exc:
        db.rollback()
        run = db.get(IngestionRun, run.id)
        run.status = "failed"
        run.error_class = type(exc).__name__
        run.error_message = str(exc)[:2000]
        run.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    return run


def bootstrap_next_market_history(db: Session) -> IngestionRun | None:
    if not settings.market_history_bootstrap_enabled or settings.market_data_mode in {"mock", "vendor"}:
        return None
    end = date.today()
    start = end - timedelta(days=settings.market_history_years * 366)
    minimum_rows = int(settings.market_history_years * 252 * 0.80)
    for symbol in settings.market_data_default_symbols:
        count = len(price_series(db, symbol, start, end))
        if count < minimum_rows:
            return run_historical_backfill(
                db,
                provider_name="auto" if settings.market_data_mode == "auto" else settings.market_data_mode,
                symbols=[symbol],
                start=start,
                end=end,
                run_key=f"bootstrap:{symbol}:{start}:{end}",
            )
    return None
