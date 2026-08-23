import json
from datetime import UTC, datetime

import numpy as np
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.user import User
from app.models.workstation import (
    Event,
    EventEntityLink,
    EventSource,
    DataSource,
    FinancialFact,
    Instrument,
    InstrumentAlias,
    MacroObservation,
    MacroSeries,
    MacroSeriesProvider,
    SourceArtifact,
    StandardizedFinancialFact,
)
from app.schemas.research import InstrumentResponse
from app.services.portfolio_service import get_portfolio_summary
from app.services.canonical_market_service import latest_price, price_series
from app.services.company_event_service import sourced_company_events
from app.domain.quant import risk_metrics
from app.domain.quant import market_model_event_study
from app.schemas.research import EventStudyRequest


FACT_ALIASES = {
    "revenue": {"revenue", "sales", "net_sales"},
    "ebit": {"ebit", "operating_profit", "profit_from_operations"},
    "net_income": {"net_income", "profit_after_tax", "profit_for_the_year"},
    "eps": {"eps", "earnings_per_share", "basic_eps"},
    "assets": {"assets", "total_assets"},
    "equity": {"equity", "total_equity", "shareholders_equity"},
    "debt": {"debt", "total_debt", "borrowings"},
    "cash": {"cash", "cash_and_cash_equivalents"},
    "free_cash_flow": {"free_cash_flow", "fcf"},
    "dividend": {"dividend", "dividend_per_share", "dps"},
}


def _normalized_taxonomy(key: str) -> str:
    return key.lower().replace(".", "_").replace("-", "_").strip("_")


def _display_facts(rows: list[FinancialFact]) -> list[FinancialFact]:
    """Return the latest filed version of each economic fact for user-facing research."""
    result: list[FinancialFact] = []
    seen: set[tuple[object, ...]] = set()
    for row in sorted(rows, key=lambda item: (item.period_end, item.version, item.filing_date or item.period_end), reverse=True):
        normalized = _normalized_taxonomy(row.taxonomy_key)
        canonical = next((name for name, aliases in FACT_ALIASES.items() if normalized in aliases), normalized)
        key = (canonical, row.period_type, row.period_end, row.unit, row.currency, row.consolidated)
        if key not in seen:
            result.append(row)
            seen.add(key)
    return result


def _display_documents(rows: list[Document]) -> list[Document]:
    """Collapse re-ingested versions of the same reporting period in the research UI."""
    result: list[Document] = []
    seen: set[tuple[object, ...]] = set()
    for row in rows:
        key = (row.document_type, row.published_date, row.fiscal_year, row.quarter)
        if key not in seen:
            result.append(row)
            seen.add(key)
    return result


def _document_provenance(db: Session, document_ids: set[str]) -> dict[str, dict[str, object]]:
    if not document_ids:
        return {}
    return {
        row.id: {
            "source_name": row.source_name,
            "document_type": row.document_type,
            "is_synthetic": (
                row.document_type == "synthetic_demo_facts"
                or "demo" in (row.source_name or "").lower()
                or (row.source_url or "").lower().startswith("demo://")
            ),
            "is_observed": bool(
                row.source_name
                and row.source_url
                and not (
                    row.document_type == "synthetic_demo_facts"
                    or "demo" in row.source_name.lower()
                    or row.source_url.lower().startswith("demo://")
                )
            ),
            "ingested_at": row.parsed_at or row.downloaded_at or row.created_at,
        }
        for row in db.scalars(select(Document).where(Document.id.in_(document_ids)))
    }


def _fact_provenance(provenance: dict[str, dict[str, object]], document_id: str | None) -> dict[str, object]:
    if document_id and document_id in provenance:
        return provenance[document_id]
    return {"source_name": None, "document_type": None, "is_synthetic": False, "is_observed": False, "ingested_at": None}


def _group_provenance(provenance: dict[str, dict[str, object]], document_ids: list[str | None]) -> dict[str, object]:
    resolved = [provenance[document_id] for document_id in document_ids if document_id and document_id in provenance]
    return {
        "is_synthetic": any(item["is_synthetic"] for item in resolved),
        "sources": sorted({str(item["source_name"]) for item in resolved if item["source_name"]}),
    }


def _derived_fundamentals(facts: list[FinancialFact], provenance: dict[str, dict[str, object]] | None = None) -> dict[str, object]:
    provenance = provenance or {}
    grouped: dict[str, list[FinancialFact]] = {}
    for fact in facts:
        normalized = _normalized_taxonomy(fact.taxonomy_key)
        canonical = next((name for name, aliases in FACT_ALIASES.items() if normalized in aliases), normalized)
        grouped.setdefault(canonical, []).append(fact)
    latest: dict[str, FinancialFact] = {}
    growth: dict[str, object] = {}
    for key, rows in grouped.items():
        rows.sort(key=lambda row: (row.period_end, row.version), reverse=True)
        latest[key] = rows[0]
        comparable = next((row for row in rows[1:] if row.unit == rows[0].unit and row.currency == rows[0].currency and row.period_type == rows[0].period_type), None)
        if comparable and comparable.value != 0:
            growth[key] = {
                "value": float((rows[0].value / comparable.value) - 1),
                "current_period": rows[0].period_end,
                "comparison_period": comparable.period_end,
                "document_ids": [rows[0].document_id, comparable.document_id],
            }

    ratios: dict[str, object] = {}
    revenue = latest.get("revenue")
    net_income = latest.get("net_income")
    ebit = latest.get("ebit")
    assets = latest.get("assets")
    equity = latest.get("equity")

    def compatible(left: FinancialFact | None, right: FinancialFact | None) -> bool:
        return bool(left and right and left.period_end == right.period_end and left.unit == right.unit and left.currency == right.currency and right.value != 0)

    if compatible(ebit, revenue):
        ratios["operating_margin"] = {"value": float(ebit.value / revenue.value), "period_end": revenue.period_end, "document_ids": [ebit.document_id, revenue.document_id]}
    if compatible(net_income, revenue):
        ratios["net_margin"] = {"value": float(net_income.value / revenue.value), "period_end": revenue.period_end, "document_ids": [net_income.document_id, revenue.document_id]}
    if compatible(net_income, assets):
        ratios["return_on_assets_unaveraged"] = {"value": float(net_income.value / assets.value), "period_end": assets.period_end, "document_ids": [net_income.document_id, assets.document_id], "warning": "Uses period-end assets because average assets are unavailable."}
    if compatible(net_income, equity):
        ratios["return_on_equity_unaveraged"] = {"value": float(net_income.value / equity.value), "period_end": equity.period_end, "document_ids": [net_income.document_id, equity.document_id], "warning": "Uses period-end equity because average equity is unavailable."}
    for entry in growth.values():
        entry["provenance"] = _group_provenance(provenance, entry["document_ids"])
    for entry in ratios.values():
        entry["provenance"] = _group_provenance(provenance, entry["document_ids"])
    return {
        "latest": {key: {"value": value.value, "unit": value.unit, "currency": value.currency, "period_end": value.period_end, "document_id": value.document_id, "page_number": value.page_number, "provenance": _fact_provenance(provenance, value.document_id)} for key, value in latest.items()},
        "growth": growth,
        "ratios": ratios,
        "valuation": {"available": False, "reason": "Canonical share-count and fully diluted valuation inputs are not available."},
    }


def _market_research(db: Session, instrument: Instrument) -> dict[str, object]:
    rows = price_series(db, instrument.symbol)
    if not rows:
        return {"available": False, "reason": "No canonical market observations are available."}
    result: dict[str, object] = {
        "available": True,
        "start_date": rows[0].trade_date,
        "end_date": rows[-1].trade_date,
        "sample_size": len(rows),
        "latest": {"close": rows[-1].close, "volume": rows[-1].volume, "source": rows[-1].source, "artifact_id": rows[-1].artifact_id, "adjustment_state": rows[-1].adjustment_state},
        "liquidity": {
            "average_daily_volume": float(np.mean([row.volume for row in rows[-60:]])),
            "average_daily_traded_value": float(np.mean([float(row.value) for row in rows[-60:]])),
            "window": min(60, len(rows)),
        },
    }
    if len(rows) >= 31:
        closes = np.asarray([float(row.close) for row in rows])
        returns = closes[1:] / closes[:-1] - 1
        result["risk"] = risk_metrics(returns).to_dict()
    else:
        result["risk"] = {"available": False, "reason": "At least 31 price observations are required."}
    result["benchmark_comparison"] = {"available": False, "reason": "No benchmark was supplied for this company-research request."}
    states = {row.adjustment_state for row in rows}
    adjustment_state = "adjusted" if states == {"adjusted"} else ("unadjusted" if "unadjusted" in states else "uncertain")
    result["adjustment_state"] = adjustment_state
    if len(rows) >= 2 and rows[0].close:
        result["price_return"] = float(rows[-1].close / rows[0].close - 1)
        result["price_return_available"] = True
    else:
        result["price_return_available"] = False
    if adjustment_state != "adjusted":
        result["adjustment_warning"] = "Corporate-action adjustment coverage is incomplete. This result may be distorted by splits, bonus issues, rights issues or other capital actions."
    result["total_return_available"] = False
    result["total_return_unavailable_reason"] = "Dividend/cash-distribution coverage is not certified complete; observed price return is shown separately."
    return result


def serialize_instrument(row: Instrument) -> InstrumentResponse:
    return InstrumentResponse(id=row.id, symbol=row.symbol, name=row.name, instrument_type=row.instrument_type, currency=row.currency, country=row.country, sector=row.sector, active_from=row.active_from, active_to=row.active_to, metadata=json.loads(row.metadata_json))


def search_instruments(db: Session, query: str | None = None, instrument_type: str | None = None, sector: str | None = None, limit: int = 50):
    statement = select(Instrument)
    if query:
        term = f"%{query.strip()}%"
        statement = statement.where(or_(Instrument.symbol.ilike(term), Instrument.name.ilike(term)))
    if instrument_type: statement = statement.where(Instrument.instrument_type == instrument_type)
    if sector: statement = statement.where(Instrument.sector == sector)
    return [serialize_instrument(row) for row in db.scalars(statement.order_by(Instrument.symbol).limit(limit))]


def instrument_detail(db: Session, instrument_id: str):
    row = db.get(Instrument, instrument_id)
    if row is None: raise HTTPException(status_code=404, detail="Instrument not found")
    aliases = [{"provider": alias.provider, "alias": alias.alias, "valid_from": alias.valid_from, "valid_to": alias.valid_to} for alias in db.scalars(select(InstrumentAlias).where(InstrumentAlias.instrument_id == row.id))]
    return {**serialize_instrument(row).model_dump(), "aliases": aliases}


def market_series(db: Session, instrument_id: str, start=None, end=None):
    instrument = db.get(Instrument, instrument_id)
    if instrument is None: raise HTTPException(status_code=404, detail="Instrument not found")
    rows = price_series(db, instrument.symbol, start, end)
    return {"instrument_id": instrument.id, "symbol": instrument.symbol, "series": [{"date": row.trade_date, "open": row.open, "high": row.high, "low": row.low, "close": row.close, "volume": row.volume, "source": row.source, "source_url": row.source_url, "artifact_id": row.artifact_id, "artifact_sha256": row.artifact_sha256, "observed_at": row.observed_at, "quality_status": row.quality_status, "adjustment_state": row.adjustment_state} for row in rows]}


def list_macro_series(db: Session):
    statement = select(MacroSeries)
    if not settings.is_synthetic_environment:
        statement = statement.join(DataSource, DataSource.id == MacroSeries.source_id).where(~func.lower(DataSource.name).contains("demo"))
    return [{"id": row.id, "key": row.key, "name": row.name, "unit": row.unit, "frequency": row.frequency, "metadata": json.loads(row.metadata_json)} for row in db.scalars(statement.order_by(MacroSeries.key))]


def macro_releases(db: Session, series_id: str | None = None):
    statement = (
        select(MacroObservation, MacroSeries, MacroSeriesProvider, DataSource)
        .join(MacroSeries, MacroSeries.id == MacroObservation.series_id)
        .outerjoin(MacroSeriesProvider, MacroSeriesProvider.id == MacroObservation.provider_id)
        .outerjoin(SourceArtifact, SourceArtifact.id == MacroObservation.artifact_id)
        .outerjoin(DataSource, DataSource.id == SourceArtifact.data_source_id)
        .where(MacroObservation.is_selected.is_(True))
    )
    if not settings.is_synthetic_environment:
        statement = statement.where(~func.lower(DataSource.name).contains("demo"), ~func.lower(SourceArtifact.source_url).like("demo://%"))
    if series_id: statement = statement.where(MacroObservation.series_id == series_id)
    return [
        {
            "series_id": series.id,
            "series_key": series.key,
            "effective_date": observation.effective_date,
            "release_at": observation.release_at,
            "value": observation.value,
            "unit": series.unit,
            "revision": observation.revision,
            "artifact_id": observation.artifact_id,
            "provider": provider.provider_key if provider else None,
            "source": data_source.name if data_source else None,
            "source_series_id": observation.source_series_id,
            "retrieved_at": observation.retrieved_at,
            "vintage_date": observation.vintage_date,
            "authority": observation.authority,
            "confidence": observation.confidence,
            "selection_reason": (
                json.loads(observation.selection_reason)
                if observation.selection_reason
                else None
            ),
        }
        for observation, series, provider, data_source in db.execute(
            statement.order_by(MacroObservation.effective_date.desc()).limit(500)
        )
    ]


def company_overview(db: Session, user: User, instrument_id: str, *, include_portfolio_relevance: bool = True):
    instrument = db.get(Instrument, instrument_id)
    if instrument is None: raise HTTPException(status_code=404, detail="Instrument not found")
    latest = latest_price(db, instrument.symbol)
    all_facts = list(db.scalars(select(FinancialFact).where(FinancialFact.instrument_id == instrument.id).order_by(FinancialFact.period_end.desc(), FinancialFact.version.desc()).limit(200)))
    all_provenance = _document_provenance(db, {fact.document_id for fact in all_facts if fact.document_id})
    observed_facts = [
        fact
        for fact in all_facts
        if all_provenance.get(fact.document_id or "", {}).get("is_observed", False)
    ]
    facts = _display_facts(observed_facts)
    standardized_facts = list(
        db.scalars(
            select(StandardizedFinancialFact)
            .where(
                StandardizedFinancialFact.instrument_id == instrument.id,
                StandardizedFinancialFact.quality_status == "observed",
            )
            .order_by(StandardizedFinancialFact.period_end.desc(), StandardizedFinancialFact.retrieved_at.desc())
            .limit(200)
        )
    )
    provenance = _document_provenance(db, {fact.document_id for fact in facts if fact.document_id})
    market_research = _market_research(db, instrument)
    documents = _display_documents(list(db.scalars(select(Document).where(Document.symbol == instrument.symbol, Document.document_type != "synthetic_demo_facts", ~func.lower(Document.source_name).contains("demo"), or_(Document.source_url.is_(None), ~func.lower(Document.source_url).like("demo://%")), or_(Document.visibility == "public", Document.owner_user_id == user.id)).order_by(Document.published_date.desc(), Document.created_at.desc()).limit(50))))[:20]
    company_events = sourced_company_events(db, instrument)
    relevance = []
    from app.models.portfolio import Portfolio, PortfolioHolding
    relevance_rows = db.execute(select(Portfolio, PortfolioHolding).join(PortfolioHolding, PortfolioHolding.portfolio_id == Portfolio.id).where(Portfolio.user_id == user.id, PortfolioHolding.symbol == instrument.symbol)) if include_portfolio_relevance else []
    for portfolio, holding in relevance_rows:
        summary = get_portfolio_summary(db, user, portfolio.id)
        item = next((value for value in summary.holdings if value.symbol == instrument.symbol), None)
        risk_context: dict[str, object] = {"available": False, "reason": "Portfolio quant inputs are unavailable."}
        try:
            from app.services.workstation_service import portfolio_quant
            quant = portfolio_quant(db, user, portfolio.id)
            symbols = quant["symbols"]
            index = symbols.index(instrument.symbol)
            covariance = np.asarray(quant["covariance"], dtype=float)
            current_values = np.asarray([float(next(value.market_value for value in summary.holdings if value.symbol == symbol)) for symbol in symbols])
            weights = current_values / current_values.sum()
            without = np.delete(weights, index)
            without /= without.sum() if without.sum() else 1
            covariance_without = np.delete(np.delete(covariance, index, axis=0), index, axis=1)
            risk_context = {
                "available": True,
                "component_risk_percent": quant["risk_contributions"].get(instrument.symbol),
                "portfolio_volatility": float(np.sqrt(weights @ covariance @ weights)),
                "volatility_without_position": float(np.sqrt(without @ covariance_without @ without)) if without.size else 0.0,
                "method": "current_weights_same_covariance_remove_and_renormalize",
            }
        except (HTTPException, ValueError, StopIteration):
            pass
        relevance.append({"portfolio_id": portfolio.id, "portfolio_name": portfolio.name, "quantity": holding.quantity, "market_value": item.market_value if item else 0, "weight": float(item.market_value / summary.total_value) if item and summary.total_value else 0, "risk_context": risk_context})
    return {
        "instrument": serialize_instrument(instrument).model_dump(),
        "market": None if latest is None else {"date": latest.trade_date, "close": latest.close, "volume": latest.volume, "change_percent": latest.change_percent, "source": latest.source, "source_url": latest.source_url, "artifact_id": latest.artifact_id, "artifact_sha256": latest.artifact_sha256, "quality_status": latest.quality_status, "adjustment_state": latest.adjustment_state},
        "market_research": market_research,
        "fundamentals": [
            *[{"taxonomy_key": fact.taxonomy_key, "period_type": fact.period_type, "period_end": fact.period_end, "filing_date": fact.filing_date, "value": fact.value, "unit": fact.unit, "currency": fact.currency, "document_id": fact.document_id, "page_number": fact.page_number, "classification": "filing_extracted", "source_url": provenance.get(fact.document_id or "", {}).get("source_url"), "provenance": _fact_provenance(provenance, fact.document_id)} for fact in facts],
            *[
                {
                    "taxonomy_key": fact.metric,
                    "period_type": fact.period_type,
                    "period_end": fact.period_end,
                    "filing_date": None,
                    "value": fact.value,
                    "unit": fact.unit,
                    "currency": fact.currency,
                    "document_id": None,
                    "page_number": None,
                    "classification": fact.classification,
                    "source_url": fact.source_url,
                    "provenance": {
                        "source_name": fact.source.upper(),
                        "document_type": "standardized_financials",
                        "is_synthetic": False,
                        "is_observed": True,
                        "ingested_at": fact.retrieved_at,
                    },
                }
                for fact in standardized_facts
                if not any(
                    _normalized_taxonomy(existing.taxonomy_key) == _normalized_taxonomy(fact.metric)
                    and existing.period_type == fact.period_type
                    and existing.period_end == fact.period_end
                    for existing in facts
                )
            ],
        ],
        "derived_fundamentals": _derived_fundamentals(facts, provenance),
        "documents": [{"id": document.id, "title": document.title, "document_type": document.document_type, "published_date": document.published_date, "source_url": document.source_url, "is_synthetic": document.document_type == "synthetic_demo_facts"} for document in documents],
        "events": [
            {
                "id": event.id,
                "title": event.title,
                "event_type": event.event_type,
                "occurred_at": event.occurred_at,
                "direction": event.direction,
                "confidence": event.confidence,
                "sources": [
                    {
                        "source_name": source.source_name,
                        "source_url": source.source_url,
                        "published_at": source.published_at,
                        "selection_status": source.selection_status,
                    }
                    for source in event_sources
                ],
            }
            for row in company_events
            for event in (row.event,)
            for event_sources in (row.sources,)
        ],
        "portfolio_relevance": relevance,
        "has_synthetic_data": False,
        "excluded_synthetic_research": len(observed_facts) != len(all_facts),
    }


def list_events(
    db: Session,
    entity_key: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
):
    statement = select(Event)
    if entity_key:
        statement = statement.join(EventEntityLink, EventEntityLink.event_id == Event.id).where(EventEntityLink.entity_key == entity_key.upper())
    if event_type:
        statement = statement.where(Event.event_type == event_type)
    rows = list(db.scalars(statement.order_by(Event.occurred_at.desc()).limit(limit)))
    result = []
    for event in rows:
        sources = list(db.scalars(select(EventSource).where(EventSource.event_id == event.id)))
        result.append({"id": event.id, "event_type": event.event_type, "title": event.title, "occurred_at": event.occurred_at, "materiality": event.materiality, "direction": event.direction, "confidence": event.confidence, "details": json.loads(event.details_json), "sources": [{"source_name": source.source_name, "source_url": source.source_url, "document_id": source.document_id} for source in sources]})
    return result


def run_event_study(db: Session, payload: EventStudyRequest):
    instrument = db.get(Instrument, payload.instrument_id)
    benchmark = db.get(Instrument, payload.benchmark_instrument_id)
    if instrument is None or benchmark is None:
        raise HTTPException(status_code=404, detail="Instrument or benchmark not found")
    asset_rows = price_series(db, instrument.symbol)
    benchmark_rows = price_series(db, benchmark.symbol)
    asset = {row.trade_date: float(row.close) for row in asset_rows}
    market = {row.trade_date: float(row.close) for row in benchmark_rows}
    price_dates = sorted(set(asset) & set(market))
    if len(price_dates) < payload.estimation_window + payload.estimation_gap + payload.pre_sessions + payload.post_sessions + 2:
        raise HTTPException(status_code=422, detail="Insufficient aligned canonical history for the requested event-study windows")
    return_dates = price_dates[1:]
    asset_returns = np.asarray([asset[price_dates[index]] / asset[price_dates[index - 1]] - 1 for index in range(1, len(price_dates))])
    benchmark_returns = np.asarray([market[price_dates[index]] / market[price_dates[index - 1]] - 1 for index in range(1, len(price_dates))])
    result = market_model_event_study(return_dates, asset_returns, benchmark_returns, payload.event_dates, estimation_window=payload.estimation_window, estimation_gap=payload.estimation_gap, pre_sessions=payload.pre_sessions, post_sessions=payload.post_sessions)
    return {"instrument": instrument.symbol, "benchmark": benchmark.symbol, "price_source_artifacts": sorted({row.artifact_id for row in [*asset_rows, *benchmark_rows] if row.artifact_id}), **result}
