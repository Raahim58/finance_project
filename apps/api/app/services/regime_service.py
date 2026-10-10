"""Deterministic macro/market regime classification from structured observations."""

from datetime import date,timedelta
from time import monotonic
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.core.config import settings
from app.models.workstation import DataSource, MacroObservation, MacroSeries, SourceArtifact
from app.services.market_service import get_sectors
from app.services.portfolio_service import get_portfolio_summary


DIMENSION_TERMS = {
    "rates": ("policy rate", "interest rate", "yield", "kibor", "tbill"),
    "currency": ("usd/pkr", "pkr", "exchange rate", "fx"),
    "inflation": ("inflation", "cpi"),
    "oil": ("brent", "crude", "oil price"),
}


def _series_dimension(series: MacroSeries) -> str | None:
    label = f"{series.key} {series.name}".lower().replace("_", " ").replace(".", " ")
    return next((dimension for dimension, terms in DIMENSION_TERMS.items() if any(term in label for term in terms)), None)


def _latest_pair(db: Session, series: MacroSeries) -> list[MacroObservation]:
    statement = select(MacroObservation).where(MacroObservation.series_id == series.id, MacroObservation.is_selected.is_(True),MacroObservation.effective_date<=date.today())
    if not settings.is_synthetic_environment:
        statement = (
            statement
            .join(SourceArtifact, SourceArtifact.id == MacroObservation.artifact_id)
            .join(DataSource, DataSource.id == SourceArtifact.data_source_id)
            .where(~func.lower(DataSource.name).contains("demo"), ~func.lower(SourceArtifact.source_url).like("demo://%"))
        )
    rows=list(db.scalars(statement.order_by(MacroObservation.effective_date.desc(), MacroObservation.revision.desc()).limit(6)))
    unique={}
    for row in rows: unique.setdefault(row.effective_date,row)
    return list(unique.values())[:2]


_SECTOR_CACHE: dict[str, object] = {}
_SECTOR_TTL_SECONDS = 120


def _breadth_sectors(db: Session):
    """Sector breadth changes at most per session; a short cache keeps the Today page off cold price queries."""
    now = monotonic()
    cached = None if settings.is_synthetic_environment else _SECTOR_CACHE.get("rows")
    if cached is not None and now - _SECTOR_CACHE["at"] < _SECTOR_TTL_SECONDS:
        return cached
    try:
        rows = get_sectors(db)
    except Exception:
        return []
    _SECTOR_CACHE.update(rows=rows, at=now)
    return rows


def macro_regime(db: Session, user: User, portfolio_id: str | None = None) -> dict[str, object]:
    dimensions: dict[str, dict[str, object]] = {}
    for series in db.scalars(select(MacroSeries).order_by(MacroSeries.key)):
        dimension = _series_dimension(series)
        if not dimension:
            continue
        if dimension=="currency" and series.unit.lower().replace("_"," ").replace("/"," per ") not in {"pkr per usd","pkr usd"}: continue
        observations = _latest_pair(db, series)
        if not observations:
            continue
        latest = observations[0]
        previous = observations[1] if len(observations) > 1 else None
        if dimension in dimensions and dimensions[dimension]["effective_date"]>=latest.effective_date: continue
        change = latest.value - previous.value if previous else None
        trend = "not_evaluated" if change is None else "rising" if change > 0 else "falling" if change < 0 else "flat"
        age=(date.today()-latest.effective_date).days
        limits={'daily':7,'weekly':21,'monthly':62,'quarterly':150,'annual':550,'mixed':62}
        stale=age>limits.get(series.frequency,62)
        artifact=db.get(SourceArtifact,latest.artifact_id) if latest.artifact_id else None
        dimensions[dimension] = {"status":"stale" if stale else trend,"trend":trend,"freshness_status":"stale" if stale else "current",
            "series_key":series.key,"series_name":series.name,"value":str(latest.value),
            "previous_value":str(previous.value) if previous else None,"change":str(change) if change is not None else None,
            "change_kind":"absolute_in_series_unit","unit":series.unit,"effective_date":latest.effective_date,
            "release_at":latest.release_at,"artifact_id":latest.artifact_id,"observation_id":latest.id,
            "revision":latest.revision,"source_url":artifact.source_url if artifact else None,
            "age_days":age,"freshness_limit_days":limits.get(series.frequency,62)}
        if dimension=='currency' and previous and previous.value>0:
            dimensions[dimension]['quote_change_percent']=str(change/previous.value*Decimal(100))
            dimensions[dimension]['pkr_direction']='appreciation' if change<0 else 'depreciation' if change>0 else 'unchanged'


    sectors = _breadth_sectors(db)
    advancers = sum(row.advancers for row in sectors)
    decliners = sum(row.decliners for row in sectors)
    if advancers or decliners:
        dimensions["market_breadth"] = {"status": "positive" if advancers > decliners else "negative" if decliners > advancers else "flat", "advancers": advancers, "decliners": decliners, "trade_date": max(row.trade_date for row in sectors), "source": sorted({row.source for row in sectors})}

    if "market_breadth" in dimensions:
        breadth=dimensions["market_breadth"]
        breadth["freshness_status"]="stale" if breadth["trade_date"]<date.today()-timedelta(days=7) else "current"
        if breadth["freshness_status"]=="stale": breadth["status"]="stale"
    stress_signals = []
    if dimensions.get("rates", {}).get("status") == "rising": stress_signals.append("rates")
    if dimensions.get("currency", {}).get("status") == "rising": stress_signals.append("currency")
    if dimensions.get("inflation", {}).get("status") == "rising": stress_signals.append("inflation")
    if dimensions.get("market_breadth", {}).get("status") == "negative": stress_signals.append("market_breadth")
    evaluable = [value for value in dimensions.values() if value.get("status") not in ("not_evaluated","stale")]
    regime = "not_evaluated" if len(evaluable) < 2 else "risk_off" if len(stress_signals) >= 2 else "constructive" if not stress_signals and dimensions.get("market_breadth", {}).get("status") == "positive" else "mixed"
    suggested = []
    if "market_breadth" in stress_signals: suggested.append("psx_drawdown")
    if "rates" in stress_signals: suggested.append("rate_shock")
    if "currency" in stress_signals: suggested.append("pkr_depreciation")
    if dimensions.get("oil", {}).get("status") == "rising": suggested.append("oil_spike")

    relevance = None
    if portfolio_id:
        summary = get_portfolio_summary(db, user, portfolio_id)
        relevance = {"portfolio_id": portfolio_id, "sectors": sorted({holding.sector for holding in summary.holdings if holding.sector}), "suggested_scenario_ids": suggested}
    return {"regime": regime, "method": "rule_based_v2", "method_note": "Classification uses direction of selected structured observations and market breadth. It is a scenario-routing heuristic, not a forecast.", "stale_dimensions":[key for key,value in dimensions.items() if value.get("freshness_status")=="stale"], "dimensions": dimensions, "stress_signals": stress_signals, "suggested_scenario_ids": suggested, "portfolio_relevance": relevance}
