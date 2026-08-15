from calendar import monthrange
from datetime import UTC, date, datetime
from decimal import Decimal
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import Date, cast, select

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.workstation import FinancialFact, Instrument, MarketObservation, SourceArtifact, StandardizedFinancialFact
from app.providers.fundamentals.dps_standardized import DpsStandardizedFundamentalsProvider
from app.providers.fundamentals.psx_financials import PsxFinancialsProvider, ReportCatalogItem
from app.providers.fundamentals.extraction import extract_facts, parse_financial_pdf, parse_period_end
from app.services.canonical_market_service import reconcile_market_observations
from app.services.coverage_service import begin, complete, coverage, fail
from app.services.ingestion_persistence import source, store_artifact
from app.services.market_ingestion import persist_market_data
from app.services.market_providers import DpsMarketDataProvider
from app.services.rag_service import create_document_from_pages, parse_pdf


RETRY = dict(autoretry_for=(httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError), retry_backoff=True, retry_backoff_max=900, retry_jitter=True, max_retries=5)


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
        if state.status == "complete":
            return {"symbol": instrument.symbol, "status": "complete", "idempotent": True, "facts": state.item_count}
        begin(state); db.commit()
        try:
            content, facts, diagnostics, url = DpsStandardizedFundamentalsProvider().fetch(instrument.symbol)
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
                row.classification = "standardized_secondary"; row.quality_status = "observed"; row.retrieved_at = datetime.now(UTC)
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
        if state.status == "complete":
            return {"symbol": instrument.symbol, "period": period_key, "status": "complete", "idempotent": True, "rows": state.item_count}
        begin(state); db.commit()
        try:
            start = date(year, month, 1); end = date(year, month, monthrange(year, month)[1])
            provider = DpsMarketDataProvider()
            rows = provider.fetch_symbol_history(instrument.symbol, start, end)
            if not rows:
                raise ValueError(f"DPS returned no validated OHLCV for {instrument.symbol} {period_key}")
            data_source = source(db, "PSX DPS", "market", "https://dps.psx.com.pk", 10, 1440, "Observed DPS OHLCV; raw monthly responses are retained.")
            raw_artifacts = [store_artifact(db, data_source, captured["content"], url=captured["url"], method=captured["method"], parser_version=provider.parser_version, content_type=captured["content_type"] or "text/html", effective_at=datetime.combine(start, datetime.min.time(), tzinfo=UTC)) for captured in provider.captured_responses]
            result = persist_market_data(db, latest_prices=rows, source="dps")
            if raw_artifacts:
                for observation in db.scalars(select(MarketObservation).join(SourceArtifact, SourceArtifact.id == MarketObservation.artifact_id).where(
                    MarketObservation.instrument_id == instrument.id,
                    cast(MarketObservation.effective_at, Date) >= start,
                    cast(MarketObservation.effective_at, Date) <= end,
                    MarketObservation.frequency == "daily",
                    SourceArtifact.source_url.like("normalized://dps/%"),
                )):
                    observation.artifact_id = raw_artifacts[0].id
                db.flush()
                for row in rows:
                    reconcile_market_observations(
                        db,
                        instrument_id=instrument.id,
                        effective_at=datetime.combine(row.trade_date, datetime.min.time(), tzinfo=ZoneInfo("Asia/Karachi")),
                    )
            complete(state, len(rows), [f"canonical_observations={result.get('canonical_observations', 0)}", f"raw_artifacts={len(raw_artifacts)}"]); db.commit()
            return {"symbol": instrument.symbol, "period": period_key, "status": "complete", "rows": len(rows)}
        except Exception as exc:
            db.rollback(); state = coverage(db, instrument.id, "price_history", period_key, "dps"); fail(state, exc); db.commit(); raise


def _item(payload: dict[str, object]) -> ReportCatalogItem:
    return ReportCatalogItem(symbol=str(payload["symbol"]), report_type=str(payload["report_type"]), period_ended=str(payload["period_ended"]), posting_date=date.fromisoformat(str(payload["posting_date"])), report_url=str(payload["report_url"]), report_id=str(payload["report_id"]))


@celery_app.task(name="phase2.financial_download_catalog", **RETRY)
def financial_download_catalog(symbol: str, mode: str = "incremental", as_of_year: int | None = None) -> dict[str, object]:
    if mode not in {"historical", "incremental"}:
        raise ValueError("mode must be historical or incremental")
    with SessionLocal() as db:
        instrument = _instrument(db, symbol)
        provider = PsxFinancialsProvider(); year = as_of_year or date.today().year
        years = range(year, year - 6, -1) if mode == "historical" else (year, year - 1)
        discovered: dict[str, ReportCatalogItem] = {}
        for catalog_year in years:
            state = coverage(db, instrument.id, "report_catalog", str(catalog_year), "psx_financials")
            if state.status == "complete":
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
                db.rollback(); state = coverage(db, instrument.id, "report_catalog", str(catalog_year), "psx_financials"); fail(state, exc); db.commit(); raise
        selected: list[ReportCatalogItem] = []
        annual = interim = 0
        for item in sorted(discovered.values(), key=lambda value: value.posting_date, reverse=True):
            is_annual = "annual" in item.report_type
            if is_annual and annual < 5: selected.append(item); annual += 1
            elif not is_annual and interim < 8: selected.append(item); interim += 1
        queued = 0
        for item in selected:
            state = coverage(db, instrument.id, "financial_report", item.report_id, "psx_financials")
            if state.status in {"missing", "failed", "partial"}:
                financial_download_pdf.delay({"symbol": item.symbol, "report_type": item.report_type, "period_ended": item.period_ended, "posting_date": item.posting_date.isoformat(), "report_url": item.report_url, "report_id": item.report_id})
                queued += 1
            else:
                document = db.scalar(select(Document).where(Document.source_url == item.report_url))
                if document is not None:
                    extraction = coverage(db, instrument.id, "financial_extract", document.id, "psx_financials")
                    if extraction.status != "complete": financial_extract.delay(document.id)
        return {"symbol": instrument.symbol, "mode": mode, "catalog_items": len(discovered), "selected": len(selected), "queued": queued}


@celery_app.task(name="phase2.financial_download_pdf", **RETRY)
def financial_download_pdf(payload: dict[str, object]) -> dict[str, object]:
    item = _item(payload)
    with SessionLocal() as db:
        instrument = _instrument(db, item.symbol); state = coverage(db, instrument.id, "financial_report", item.report_id, "psx_financials")
        if state.status == "complete": return {"report_id": item.report_id, "status": "complete", "idempotent": True}
        begin(state); db.commit()
        try:
            content = PsxFinancialsProvider().fetch_report(item)
            data_source = source(db, "PSX Financials", "company_reports", "https://financials.psx.com.pk", 10, 1440, "Official PSX report catalogue and PDFs.")
            artifact = store_artifact(db, data_source, content, url=item.report_url, method="GET", parser_version="psx-financials-json-v1", content_type="application/pdf", effective_at=datetime.combine(item.posting_date, datetime.min.time(), tzinfo=UTC))
            document = db.scalar(select(Document).where(Document.source_url == item.report_url))
            if document is None:
                document = Document(symbol=item.symbol, document_type="annual_report" if "annual" in item.report_type else "interim_report", title=f"{item.symbol} {item.report_type} — {item.period_ended}", source_name="PSX Financials", source_url=item.report_url, content_hash=artifact.sha256, artifact_id=artifact.id, published_date=item.posting_date, downloaded_at=datetime.now(UTC), status="downloaded", visibility="public")
                db.add(document); db.flush()
            complete(state, 1); db.commit()
            financial_extract.delay(document.id)
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
        if state.status == "complete": return {"document_id": document.id, "status": "complete", "idempotent": True, "facts": state.item_count}
        begin(state); db.commit()
        try:
            artifact = db.get(SourceArtifact, document.artifact_id)
            if artifact is None or not artifact.storage_path: raise ValueError("Downloaded report artifact is unavailable")
            content = Path(artifact.storage_path).read_bytes(); pages, classification, parser_diagnostics = parse_financial_pdf(content)
            period_end = parse_period_end(document.title) or document.published_date
            facts, diagnostics = extract_facts(pages, period_end) if period_end else ([], ["Report period unavailable."])
            diagnostics = parser_diagnostics + diagnostics
            if classification == "scanned_or_sparse": diagnostics.append("Normal extraction was sparse; selective OCR is required but no deterministic OCR result was available, so facts remain unavailable.")
            for fact in facts if classification == "text_native" else []:
                exists = db.scalar(select(FinancialFact.id).where(FinancialFact.instrument_id == instrument.id, FinancialFact.taxonomy_key == fact.taxonomy_key, FinancialFact.period_end == fact.period_end, FinancialFact.document_id == document.id))
                if not exists:
                    db.add(FinancialFact(instrument_id=instrument.id, taxonomy_key=fact.taxonomy_key, period_type="annual" if document.document_type == "annual_report" else "interim", period_end=fact.period_end, filing_date=document.published_date, value=fact.value, unit=fact.unit, currency=fact.currency, consolidated=fact.consolidated, document_id=document.id, page_number=fact.page_number, source_label=fact.source_label, extraction_method=fact.extraction_method, confidence=fact.confidence, diagnostics_json=json.dumps({"messages": diagnostics})))
            document.status = "parsed" if classification == "text_native" else "needs_ocr"; document.extraction_version = "financial-layout-v2"; document.parsed_at = datetime.now(UTC)
            complete(state, len(facts) if classification == "text_native" else 0, diagnostics); db.commit()
            return {"document_id": document.id, "status": state.status, "classification": classification, "facts": state.item_count, "diagnostics": diagnostics}
        except Exception as exc:
            db.rollback(); state = coverage(db, instrument.id, "financial_extract", document_id, "psx_financials"); fail(state, exc); db.commit(); raise
