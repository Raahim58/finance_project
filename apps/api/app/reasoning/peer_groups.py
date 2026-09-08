from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.market import Company
from app.services.canonical_market_service import latest_price
from app.models.portfolio import PortfolioHolding
from app.models.workstation import CompanyScreeningSnapshot, Instrument


UNCLASSIFIED = "Unclassified"


def build_peer_group_packets(
    db: Session, portfolio_id: str | None
) -> dict[str, list[dict[str, object]]]:
    """Return every eligible active PSX equity exactly once, grouped by stored sector."""

    today = date.today()
    instruments = list(
        db.scalars(
            select(Instrument)
            .join(Company, Company.id == Instrument.company_id)
            .where(
                Company.is_active.is_(True),
                Instrument.instrument_type == "equity",
                (Instrument.active_from.is_(None) | (Instrument.active_from <= today)),
                (Instrument.active_to.is_(None) | (Instrument.active_to >= today)),
            )
            .order_by(Instrument.symbol)
        )
    )
    if not instruments:
        return {}

    ids = [row.id for row in instruments]
    prices = {row.symbol: latest_price(db, row.symbol) for row in instruments}

    snapshots = list(
        db.scalars(
            select(CompanyScreeningSnapshot)
            .where(CompanyScreeningSnapshot.instrument_id.in_(ids))
            .order_by(
                CompanyScreeningSnapshot.instrument_id,
                CompanyScreeningSnapshot.as_of_date.desc(),
            )
        )
    )
    latest_snapshots: dict[str, CompanyScreeningSnapshot] = {}
    for row in snapshots:
        latest_snapshots.setdefault(row.instrument_id, row)

    held = set()
    if portfolio_id:
        held = set(
            db.scalars(
                select(PortfolioHolding.instrument_id).where(
                    PortfolioHolding.portfolio_id == portfolio_id,
                    PortfolioHolding.instrument_id.is_not(None),
                )
            )
        )

    packets: dict[str, list[dict[str, object]]] = defaultdict(list)
    for instrument in instruments:
        price = prices.get(instrument.symbol)
        snapshot = latest_snapshots.get(instrument.id)
        sector = (instrument.sector or "").strip() or UNCLASSIFIED
        packets[sector].append(
            {
                "instrument_id": instrument.id,
                "symbol": instrument.symbol,
                "name": instrument.name,
                "sector": sector,
                "classification_source": "PSX symbol universe",
                "held": instrument.id in held,
                "price": None if price is None else str(price.close),
                "trade_date": None if price is None else price.trade_date.isoformat(),
                "change_percent": None if price is None else str(price.change_percent),
                "volume": None if price is None else price.volume,
                "market_cap": None if price is None or price.market_cap is None else str(price.market_cap),
                "price_source": None if price is None else price.source,
                "screening_as_of": None if snapshot is None else snapshot.as_of_date.isoformat(),
                "screening_completeness": None if snapshot is None else str(snapshot.completeness),
                "sector_percentile": None if snapshot is None or snapshot.sector_percentile is None else str(snapshot.sector_percentile),
                "metrics": {} if snapshot is None else json.loads(snapshot.metrics_json or "{}"),
                "missing": [
                    name
                    for name, value in (
                        ("latest_price", price),
                        ("screening_snapshot", snapshot),
                    )
                    if value is None
                ],
            }
        )
    return {sector: packets[sector] for sector in sorted(packets)}


def peer_packet_evidence(
    packets: dict[str, list[dict[str, object]]]
) -> list[dict[str, object]]:
    return [
        {
            "evidence_id": f"discovery:{row['instrument_id']}",
            "metric": "market_discovery_record",
            **row,
        }
        for rows in packets.values()
        for row in rows
    ]
