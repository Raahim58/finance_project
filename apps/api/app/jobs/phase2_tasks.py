from calendar import monthrange
from datetime import UTC, date, datetime
from decimal import Decimal
import json
import hashlib
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.workstation import FinancialFact, Instrument, MarketObservation, SourceArtifact, StandardizedFinancialFact
from app.providers.fundamentals.dps_standardized import DpsStandardizedFundamentalsProvider
from app.providers.fundamentals.psx_financials import PsxFinancialsProvider, ReportCatalogItem
from app.providers.fundamentals.extraction import FINANCIAL_EXTRACTION_VERSION, extract_facts, parse_financial_pdf, parse_period_end
from app.services.coverage_service import begin, complete, coverage, fail, is_queueable, reserve_and_publish
from app.services.ingestion_persistence import source, store_artifact
from app.services.market_ingestion import persist_market_data
from app.services.market_providers import DpsMarketDataProvider
from app.services.rag_service import create_document_from_pages, parse_pdf
from app.ingestion.artifact_store import get_artifact_store
from app.core.config import settings


RETRY = dict(autoretry_for=(httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError), retry_backoff=True, retry_backoff_max=900, retry_jitter=True, max_retries=3)


def _instrument(db, symbol: str) -> Instrument:
    row = db.scalar(select(Instrument).where(Instrument.symbol == symbol.strip().upper()))
    if row is None:
        raise ValueError(f"Observed instrument {symbol!r} is not present; refresh the DPS universe first")
    return row


@celery_app.task(name="phase2.broad_fundamentals", **RETRY)
def broad_fundamentals(symbol: str) -> dict[str, object]:
    with SessionLocal() as db:
        instrument = _instrument(db, symbol)
        state = coverage(db, instrument.id, "standardized_fundamentals", "current", "dps")
        if state.status in {"complete", "partial"}:
            return {"symbol": instrument.symbol, "status": state.status, "idempotent": True, "facts": state.item_count}
        begin(state); db.commit()
        try:
            calendar=json.loads(instrument.metadata_json or '{}').get('fiscal_calendar',{})
            month=calendar.get('year_end_month') if calendar.get('source_url') else None
            content, facts, diagnostics, url = DpsStandardizedFundamentalsProvider().fetch(instrument.symbol, fiscal_year_end_month=month)
            data_source = source(db, "PSX DPS standardized financials", "standardized_financials", "https://dps.psx.com.pk", 20, 43_200, "Secondary standardized company-page values; not issuer-filed canonical facts.")
            store_artifact(db, data_source, content, url=url, method="GET", parser_version="dps-company-financials-v1", content_type="text/html")
            for fact in facts:
                row = db.scalar(select(StandardizedFinancialFact).where(
                    StandardizedFinancialFact.instrument_id == instrument.id,
                    StandardizedFinancialFact.metric == fact.metric,
                    StandardizedFinancialFact.period_type == fact.period_type,
                    StandardizedFinancialFact.period_key == fact.period_key,
                    StandardizedFinancialFact.source == "dps",
                ))
                if row is None:
                    row = StandardizedFinancialFact(instrument_id=instrument.id, metric=fact.metric, period_type=fact.period_type, period_key=fact.period_key, source="dps", source_url=url, value=fact.value, unit=fact.unit)
                    db.add(row)
                row.period_end = fact.period_end; row.value = fact.value; row.unit = fact.unit; row.currency = fact.currency
                row.classification = "standardized_secondary"; row.quality_status = "observed" if fact.period_end else "needs_period_review"; row.retrieved_at = datetime.now(UTC)
            complete(state, len(facts), diagnostics); db.commit()
            return {"symbol": instrument.symbol, "status": state.status, "facts": len(facts), "diagnostics": diagnostics}
        except Exception as exc:
            db.rollback(); state = coverage(db, instrument.id, "standardized_fundamentals", "current", "dps"); fail(state, exc); db.commit(); raise


@celery_app.task(name="phase2.dps_history", **RETRY)
def dps_history(symbol: str, year: int, month: int) -> dict[str, object]:
    period_key = f"{year:04d}-{month:02d}"
    with SessionLocal() as db:
        instrument = _instrument(db, symbol)
        state = coverage(db, instrument.id, "price_history", period_key, "dps")
        month_end = date(year, month, monthrange(year, month)[1])
        # A month marked complete while it was still open must be caught up
        # once the month closes. A mid-month snapshot is not full coverage.
        if state.status == "complete" and state.completed_at is not None and state.completed_at.date() >= month_end:
            return {"symbol": instrument.symbol, "period": period_key, "status": "complete", "idempotent": True, "rows": state.item_count}
        begin(state); db.commit()
        try:
            start = date(year, month, 1); end = min(month_end, datetime.now(ZoneInfo("Asia/Karachi")).date())
            provider = DpsMarketDataProvider()
            rows = provider.fetch_symbol_history(instrument.symbol, start, end)
            if not rows:
                raise ValueError(f"DPS returned no validated OHLCV for {instrument.symbol} {period_key}")
            data_source = source(db, "PSX DPS", "market", "https://dps.psx.com.pk", 10, 1440, "Observed DPS OHLCV; raw monthly responses are retained.")
            raw_artifacts = [store_artifact(db, data_source, captured["content"], url=captured["url"], method=captured["method"], parser_version=provider.parser_version, content_type=captured["content_type"] or "text/html", effective_at=datetime.combine(start, datetime.min.time(), tzinfo=UTC)) for captured in provider.captured_responses]
            result = persist_market_data(db, latest_prices=rows, source="dps")
            if raw_artifacts:
                # Keep observation identity stable. Repointing all observations
                # to the first downloaded artifact can collide on the source
                # uniqueness key and misattribute current-month rows to the
                # previous-month lookback response.
                for artifact in db.scalars(select(SourceArtifact).join(MarketObservation, MarketObservation.artifact_id == SourceArtifact.id).where(
                    MarketObservation.instrument_id == instrument.id,
                    MarketObservation.effective_at >= datetime.combine(start, datetime.min.time(), tzinfo=ZoneInfo("Asia/Karachi")),
                    MarketObservation.effective_at < datetime.combine(end.fromordinal(end.toordinal() + 1), datetime.min.time(), tzinfo=ZoneInfo("Asia/Karachi")),
                    MarketObservation.frequency == "daily",
                    SourceArtifact.source_url.like("normalized://dps/%"),
                )).unique():
                    metadata = json.loads(artifact.response_metadata_json or "{}")
                    metadata["raw_artifact_ids"] = sorted(set(metadata.get("raw_artifact_ids", [])) | {a.id for a in raw_artifacts})
                    artifact.response_metadata_json = json.dumps(metadata, sort_keys=True)
            complete(state, len(rows), [f"canonical_observations={result.get('canonical_observations', 0)}", f"raw_artifacts={len(raw_artifacts)}"])
            if end < month_end:
                state.status = "partial"
            db.commit()
            return {"symbol": instrument.symbol, "period": period_key, "status": state.status, "rows": len(rows)}
        except Exception as exc:
            db.rollback(); state = coverage(db, instrument.id, "price_history", period_key, "dps"); fail(state, exc); db.commit(); raise


def _item(payload: dict[str, object]) -> ReportCatalogItem:
    return ReportCatalogItem(symbol=str(payload["symbol"]), report_type=str(payload["report_type"]), period_ended=str(payload["period_ended"]), posting_date=date.fromisoformat(str(payload["posting_date"])), report_url=str(payload["report_url"]), report_id=str(payload["report_id"]))


@celery_app.task(name="phase2.financial_download_catalog", **RETRY)
def financial_download_catalog(symbol: str, mode: str = "incremental", as_of_year: int | None = None, dispatch_key: str | None = None) -> dict[str, object]:
    if mode not in {"historical", "incremental"}:
        raise ValueError("mode must be historical or incremental")
    with SessionLocal() as db:
        instrument = _instrument(db, symbol)
        provider = PsxFinancialsProvider(); year = as_of_year or date.today().year
        dispatch_key = dispatch_key or f"{mode}:{year}"
        dispatch = coverage(db, instrument.id, "report_catalog_dispatch", dispatch_key, "psx_financials")
        if dispatch.status == "complete":
            return {"symbol": instrument.symbol, "mode": mode, "status": "complete", "idempotent": True}
        begin(dispatch); db.commit()
        years = range(year, year - 6, -1) if mode == "historical" else (year, year - 1)
        discovered: dict[str, ReportCatalogItem] = {}
        for catalog_year in years:
            state = coverage(db, instrument.id, "report_catalog", str(catalog_year), "psx_financials")
            if state.status == "complete" and mode == "historical":
                cached = json.loads(state.diagnostics_json or "{}").get("items", [])
                for payload in cached:
                    item = _item(payload); discovered[item.report_id] = item
                if cached:
                    continue
            begin(state); db.commit()
            try:
                items = provider.fetch_company_year_catalog(instrument.symbol, catalog_year)
                for item in items: discovered[item.report_id] = item
                complete(state, len(items))
                state.diagnostics_json = json.dumps({"items": [{"symbol": item.symbol, "report_type": item.report_type, "period_ended": item.period_ended, "posting_date": item.posting_date.isoformat(), "report_url": item.report_url, "report_id": item.report_id} for item in items]}, sort_keys=True)
                db.commit()
            except Exception as exc:
                db.rollback()
                state = coverage(db, instrument.id, "report_catalog", str(catalog_year), "psx_financials"); fail(state, exc)
                dispatch = coverage(db, instrument.id, "report_catalog_dispatch", dispatch_key, "psx_financials"); fail(dispatch, exc)
                db.commit(); raise
        selected: list[ReportCatalogItem] = []
        annual = interim = 0
        for item in sorted(discovered.values(), key=lambda value: value.posting_date, reverse=True):
            is_annual = "annual" in item.report_type
            if is_annual and annual < 5: selected.append(item); annual += 1
            elif not is_annual and interim < 8: selected.append(item); interim += 1
        queued = 0
        for item in selected:
            state = coverage(db, instrument.id, "financial_report", item.report_id, "psx_financials")
            payload = {"symbol": item.symbol, "report_type": item.report_type, "period_ended": item.period_ended, "posting_date": item.posting_date.isoformat(), "report_url": item.report_url, "report_id": item.report_id}
            now = datetime.now(UTC)
            if is_queueable(state, now) and reserve_and_publish(db, state, financial_download_pdf, (payload,), now):
                queued += 1
        dispatch = coverage(db, instrument.id, "report_catalog_dispatch", dispatch_key, "psx_financials")
        complete(dispatch, len(selected)); db.commit()
        return {"symbol": instrument.symbol, "mode": mode, "catalog_items": len(discovered), "selected": len(selected), "queued": queued}


@celery_app.task(name="phase2.financial_download_pdf", **RETRY)
def financial_download_pdf(payload: dict[str, object]) -> dict[str, object]:
    item = _item(payload)
    with SessionLocal() as db:
        instrument = _instrument(db, item.symbol); state = coverage(db, instrument.id, "financial_report", item.report_id, "psx_financials")
        if state.status == "complete" and not settings.pipeline_enabled: return {"report_id": item.report_id, "status": "complete", "idempotent": True}
        begin(state); db.commit()
        try:
            content = PsxFinancialsProvider().fetch_report(item)
            data_source = source(db, "PSX Financials", "company_reports", "https://financials.psx.com.pk", 10, 1440, "Official PSX report catalogue and PDFs.")
            artifact = store_artifact(db, data_source, content, url=item.report_url, method="GET", parser_version="psx-financials-json-v1", content_type="application/pdf", effective_at=datetime.combine(item.posting_date, datetime.min.time(), tzinfo=UTC))
            document = db.scalar(select(Document).where(Document.source_url == item.report_url,Document.content_hash==artifact.sha256).order_by(Document.created_at.desc()).limit(1))
            if document is None:
                for previous in db.scalars(select(Document).where(Document.source_url==item.report_url,Document.content_hash!=artifact.sha256,
                        Document.visibility=='public',Document.owner_user_id.is_(None),Document.portfolio_id.is_(None))):
                    previous.status='superseded'
                document = Document(symbol=item.symbol, document_type="annual_report" if "annual" in item.report_type else "interim_report", title=f"{item.symbol} {item.report_type} — {item.period_ended}", source_name="PSX Financials", source_url=item.report_url, content_hash=artifact.sha256, artifact_id=artifact.id, published_date=item.posting_date, downloaded_at=datetime.now(UTC), status="downloaded", visibility="public")
                db.add(document); db.flush()
            complete(state, 1); db.commit()
            return {"report_id": item.report_id, "document_id": document.id, "status": "complete"}
        except Exception as exc:
            db.rollback(); state = coverage(db, instrument.id, "financial_report", item.report_id, "psx_financials"); fail(state, exc); db.commit(); raise


@celery_app.task(name="phase2.financial_extract")
def financial_extract(document_id: str) -> dict[str, object]:
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if document is None: raise ValueError("Document not found")
        instrument = _instrument(db, document.symbol or "")
        state = coverage(db, instrument.id, "financial_extract", document.id, "psx_financials")
        if state.status in {"complete", "partial"} and document.extraction_version == FINANCIAL_EXTRACTION_VERSION: return {"document_id": document.id, "status": state.status, "idempotent": True, "facts": state.item_count}
        begin(state); db.commit()
        try:
            artifact = db.get(SourceArtifact, document.artifact_id)
            if artifact is None or not artifact.storage_path: raise ValueError("Downloaded report artifact is unavailable")
            content = get_artifact_store(settings).get(artifact.storage_path)
            if hashlib.sha256(content).hexdigest() != artifact.sha256 or document.content_hash != artifact.sha256:
                raise ValueError("Financial report source hash mismatch")
            pages, classification, parser_diagnostics = parse_financial_pdf(content)
            if settings.pipeline_enabled:
                from app.providers.fundamentals.extraction import explicit_report_period
                period_end=explicit_report_period(pages,document.title)
            else:
                period_end = parse_period_end(document.title)
            method = "ocr" if classification == "ocr" else "text_layout"
            confidence = Decimal("0.700000") if classification == "ocr" else Decimal("0.900000")
            facts, diagnostics = extract_facts(pages, period_end, extraction_method=method, confidence=confidence, strict=settings.pipeline_enabled) if period_end else ([], ["Report period unavailable."])
            diagnostics = parser_diagnostics + diagnostics
            if classification == "scanned_or_sparse": diagnostics.append("Normal and OCR extraction produced no deterministic financial facts; facts remain unavailable.")
            from app.services.financial_extraction_replay import save_extracted_facts
            save_extracted_facts(db, document, instrument,
                                 facts if classification in {"text_native", "ocr"} else [],
                                 diagnostics, FINANCIAL_EXTRACTION_VERSION, strict=settings.pipeline_enabled)
            document.status = "parsed" if classification in {"text_native", "ocr"} else "needs_ocr"; document.extraction_version = FINANCIAL_EXTRACTION_VERSION; document.parsed_at = datetime.now(UTC)
            complete(state, len(facts) if classification in {"text_native", "ocr"} else 0, diagnostics); db.commit()
            if document.status == "parsed":
                try:
                    if settings.pipeline_enabled:
                        from app.services.pipeline.runs import enqueue
                        enqueue(db,"report_index","document:"+document.id,{"document_id":document.id})
                        db.commit()
                        return {"document_id":document.id,"status":state.status,"classification":classification,"facts":state.item_count,"diagnostics":diagnostics}
                    financial_index.apply_async(args=[document.id], queue="financial_extract")
                except Exception:
                    diagnostics.append("Report narrative indexing could not be queued; exact facts remain saved.")
            return {"document_id": document.id, "status": state.status, "classification": classification, "facts": state.item_count, "diagnostics": diagnostics}
        except Exception as exc:
            db.rollback(); state = coverage(db, instrument.id, "financial_extract", document_id, "psx_financials"); fail(state, exc); db.commit(); raise


@celery_app.task(name="phase2.financial_index")
def financial_index(document_id: str):
    from app.services.research_evidence_service import prepare_report
    with SessionLocal() as db:
        return prepare_report(db, document_id)
