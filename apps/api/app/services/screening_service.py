from collections import defaultdict
from datetime import date
from decimal import Decimal
import json

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.market import Company, MarketPrice
from app.models.portfolio import Portfolio, PortfolioHolding
from app.models.workstation import CompanyScreeningSnapshot, Instrument, StandardizedFinancialFact


def _growth(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous)


def compute_screening_snapshots(db: Session, as_of: date | None = None) -> list[CompanyScreeningSnapshot]:
    snapshot_date = as_of or date.today()
    instruments = list(db.scalars(select(Instrument).join(Company, Company.id == Instrument.company_id).where(Company.is_active.is_(True))))
    candidates: list[tuple[Instrument, dict[str, Decimal | None], Decimal, Decimal | None, bool]] = []
    for instrument in instruments:
        rows = list(db.scalars(select(StandardizedFinancialFact).where(
            StandardizedFinancialFact.instrument_id == instrument.id,
            StandardizedFinancialFact.period_type == "annual",
        ).order_by(StandardizedFinancialFact.period_end.desc())))
        by_metric: dict[str, list[StandardizedFinancialFact]] = defaultdict(list)
        for row in rows:
            by_metric[row.metric].append(row)
        income_key = "total_income" if "BANK" in (instrument.sector or "").upper() else "revenue"
        income = by_metric[income_key]
        pat = by_metric["net_income"]
        eps = by_metric["earnings_per_share"]
        income_growth = _growth(income[0].value, income[1].value) if len(income) > 1 else None
        pat_growth = _growth(pat[0].value, pat[1].value) if len(pat) > 1 else None
        eps_growth = _growth(eps[0].value, eps[1].value) if len(eps) > 1 else None
        margin = (pat[0].value / income[0].value) if income and pat and income[0].value else None
        latest_price = db.scalar(select(MarketPrice).where(MarketPrice.symbol == instrument.symbol).order_by(MarketPrice.trade_date.desc()).limit(1))
        liquidity = Decimal(str(min(1, max(0, (latest_price.volume if latest_price else 0) / 1_000_000)))) if latest_price else None
        dimensions = [income_growth, pat_growth, eps_growth, margin, liquidity]
        available = [value for value in dimensions if value is not None]
        completeness = Decimal(len(available)) / Decimal(len(dimensions))
        # Winsorized component values keep a single noisy growth observation from dominating.
        score = sum(max(Decimal("-1"), min(Decimal("1"), value)) for value in available) / Decimal(len(available)) if available else None
        growth_flag = any(value is not None and value >= Decimal("0.25") for value in (income_growth, pat_growth, eps_growth))
        candidates.append((instrument, {"income_growth": income_growth, "pat_growth": pat_growth, "eps_growth": eps_growth, "net_margin": margin, "liquidity": liquidity}, completeness, score, growth_flag))

    by_sector: dict[str, list[tuple[Instrument, dict[str, Decimal | None], Decimal, Decimal | None, bool]]] = defaultdict(list)
    for item in candidates:
        if item[3] is not None and float(item[2]) >= settings.screening_completeness_threshold:
            by_sector[item[0].sector or "Unknown"].append(item)

    db.execute(delete(CompanyScreeningSnapshot).where(CompanyScreeningSnapshot.as_of_date == snapshot_date))
    snapshots: list[CompanyScreeningSnapshot] = []
    for item in candidates:
        instrument, metrics, completeness, score, growth_flag = item
        peers = sorted(by_sector[instrument.sector or "Unknown"], key=lambda peer: peer[3] or Decimal("-999"))
        percentile = None
        rank_from_top = None
        if item in peers:
            index = peers.index(item)
            percentile = Decimal(index + 1) / Decimal(len(peers))
            rank_from_top = len(peers) - index
        screenable = float(completeness) >= settings.screening_completeness_threshold
        promoted = bool(screenable and percentile is not None and (
            float(percentile) >= settings.screening_promotion_percentile
            or (rank_from_top or 99) <= 3
            or (growth_flag and float(percentile) >= 0.70)
        ))
        reasons = []
        if not screenable: reasons.append("insufficient_observed_data")
        if promoted: reasons.append("within_sector_candidate")
        if growth_flag: reasons.append("growth_acceleration_flag")
        snapshot = CompanyScreeningSnapshot(
            instrument_id=instrument.id, as_of_date=snapshot_date, sector=instrument.sector,
            score=score, sector_percentile=percentile, completeness=completeness,
            screenable=screenable, promoted=promoted, growth_flag=growth_flag,
            metrics_json=json.dumps({key: None if value is None else str(value) for key, value in metrics.items()}, sort_keys=True),
            reasons_json=json.dumps(reasons),
        )
        db.add(snapshot); snapshots.append(snapshot)
    db.commit()
    return snapshots


def deep_instrument_ids(db: Session) -> set[str]:
    held = set(db.scalars(select(PortfolioHolding.instrument_id).where(PortfolioHolding.instrument_id.is_not(None))))
    benchmarks = set(db.scalars(select(Portfolio.benchmark_instrument_id).where(Portfolio.benchmark_instrument_id.is_not(None))))
    candidates = set(db.scalars(select(CompanyScreeningSnapshot.instrument_id).where(CompanyScreeningSnapshot.promoted.is_(True))))
    requested = {
        row.id for row in db.scalars(select(Instrument))
        if json.loads(row.metadata_json or "{}").get("deep_requested") is True
    }
    return {value for value in held | benchmarks | candidates | requested if value}
