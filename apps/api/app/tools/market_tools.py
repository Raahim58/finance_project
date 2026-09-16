from datetime import date, timedelta
from datetime import date as MarketDate
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.services.market_service import (
    get_market_freshness, get_market_snapshot, get_top_gainers, get_top_losers,
    get_top_volume, get_sectors, resolve_market_date,
)
from app.services.research_service import list_macro_series, macro_releases, market_series
from app.models.market import Company
from app.models.workstation import CompanyScreeningSnapshot, Instrument
from app.tools.registry import ToolDefinition, ToolRegistry, tool_result
from sqlalchemy import func, select


class EmptyInput(BaseModel):
    pass


class MarketSeriesInput(BaseModel):
    instrument_id: str
    start: date | None = None
    end: date | None = None
    limit: int = Field(default=260, ge=1, le=260)


class MacroInput(BaseModel):
    series_id: str | None = None


class MarketUniverseInput(BaseModel):
    sector: str | None = Field(default=None, max_length=120)
    cursor: str | None = Field(default=None, pattern=r"^[0-9]+$")
    limit: int = Field(default=50, ge=1, le=100)
    screening_fields: list[Literal[
        "score", "sector_percentile", "completeness", "screenable", "growth_flag",
        "income_growth", "pat_growth", "eps_growth", "net_margin", "liquidity",
    ]] = Field(default_factory=list, max_length=10)


class MarketOverviewInput(BaseModel):
    sections: list[Literal["snapshot", "gainers", "losers", "volume_leaders", "sectors"]] = Field(
        default_factory=lambda: ["snapshot"], min_length=1, max_length=5
    )
    date: MarketDate | None = None
    limit: int = Field(default=10, ge=1, le=50)


def _overview(db, _user, payload: MarketOverviewInput):
    readers = {
        "snapshot": lambda day: get_market_snapshot(db, day),
        "gainers": lambda day: get_top_gainers(db, day, payload.limit),
        "losers": lambda day: get_top_losers(db, day, payload.limit),
        "volume_leaders": lambda day: get_top_volume(db, day, payload.limit),
        "sectors": lambda day: get_sectors(db, day),
    }
    try:
        effective_date = resolve_market_date(db, payload.date)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        effective_date = None
    data, sources = {}, []
    returned = 0
    for section in dict.fromkeys(payload.sections):
        value = readers[section](effective_date) if effective_date else None
        rows = value if isinstance(value, list) else [value] if value else []
        records = [row.model_dump() for row in rows]
        returned += len(records)
        data[section] = {
            "status": "available" if records else "missing",
            "effective_date": effective_date,
            "records": records,
            "coverage": {
                "returned": len(records),
                "limit": payload.limit if section in {"gainers", "losers", "volume_leaders"} else None,
                "basis": "available stored market records; not certified complete exchange coverage",
            },
        }
        for record in records:
            source = {
                "source_name": record.get("source"), "source_url": record.get("source_url"),
                "section": section, "effective_date": effective_date,
                "symbol": record.get("symbol"), "sector": record.get("sector"),
                "index_name": record.get("index_name"), "ingested_at": record.get("ingested_at"),
            }
            sources.append(source)
    return tool_result("ok" if returned else "missing", data, sources=sources, returned=returned, remaining=0)


def _freshness(db, _user, _payload: EmptyInput):
    return tool_result(
        "ok", get_market_freshness(db).model_dump(mode="json"), returned=1, remaining=0
    )


def _series(db, _user, payload: MarketSeriesInput):
    data = market_series(db, payload.instrument_id, payload.start, payload.end)
    all_rows = data["series"]
    rows = all_rows[-payload.limit :]
    sources = {}
    normalized = []
    for row in rows:
        item = dict(row)
        source_key = "|".join(
            str(item.get(key) or "")
            for key in ("source", "source_url", "artifact_id", "artifact_sha256")
        )
        source_id = f"market_source_{len(sources) + 1}"
        if source_key not in sources:
            sources[source_key] = {
                "id": source_id,
                "source_name": item.get("source"),
                "source_url": item.get("source_url"),
                "artifact_id": item.get("artifact_id"),
                "artifact_sha256": item.get("artifact_sha256"),
            }
        item["source_ref"] = sources[source_key]["id"]
        for key in ("source", "source_url", "artifact_id", "artifact_sha256"):
            item.pop(key, None)
        normalized.append(item)
    data = {**data, "series": normalized}
    remaining = max(0, len(all_rows) - len(rows))
    continuation = None
    if remaining and rows:
        first_date = rows[0].get("date")
        if isinstance(first_date, date):
            continuation = (first_date - timedelta(days=1)).isoformat()
    return tool_result(
        "ok" if rows else "missing",
        data,
        sources=list(sources.values()),
        returned=len(rows),
        remaining=remaining,
        continuation=continuation,
    )


def _macro(db, _user, payload: MacroInput):
    data = {"series": list_macro_series(db), "releases": macro_releases(db, payload.series_id)}
    return tool_result(
        "ok" if data["series"] or data["releases"] else "missing",
        data,
        returned=len(data["releases"]),
        remaining=None,
    )


def _universe(db, _user, payload: MarketUniverseInput):
    offset = int(payload.cursor or 0)
    statement = (
        select(Instrument, Company)
        .join(Company, Company.id == Instrument.company_id)
        .where(Instrument.active_to.is_(None), Company.is_active.is_(True))
    )
    if payload.sector:
        statement = statement.where(func.lower(Company.sector) == payload.sector.lower())
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.execute(
        statement.order_by(Instrument.symbol, Instrument.id).offset(offset).limit(payload.limit)
    ).all()
    data = {
        "columns": [
            "instrument_id",
            "symbol",
            "name",
            "instrument_type",
            "currency",
            "sector",
            "classification_source",
        ],
        "rows": [
            [
                instrument.id,
                instrument.symbol,
                instrument.name,
                instrument.instrument_type,
                instrument.currency,
                company.sector,
                company.psx_url,
            ]
            for instrument, company in rows
        ],
    }
    screening_sources = []
    if payload.screening_fields:
        ids = [instrument.id for instrument, _ in rows]
        latest_dates = select(
            CompanyScreeningSnapshot.instrument_id,
            func.max(CompanyScreeningSnapshot.as_of_date).label("as_of_date"),
        ).where(CompanyScreeningSnapshot.instrument_id.in_(ids)).group_by(
            CompanyScreeningSnapshot.instrument_id
        ).subquery()
        snapshots = {row.instrument_id: row for row in db.scalars(
            select(CompanyScreeningSnapshot).join(latest_dates,
                (CompanyScreeningSnapshot.instrument_id == latest_dates.c.instrument_id)
                & (CompanyScreeningSnapshot.as_of_date == latest_dates.c.as_of_date))
        )}
        fields = list(dict.fromkeys(payload.screening_fields))
        data["columns"].extend(["screening_as_of", *fields])
        for record, (instrument, _) in zip(data["rows"], rows, strict=True):
            snapshot = snapshots.get(instrument.id)
            metrics = json.loads(snapshot.metrics_json or "{}") if snapshot else {}
            record.extend([snapshot.as_of_date if snapshot else None, *[
                getattr(snapshot, field, metrics.get(field)) if snapshot else None for field in fields
            ]])
            if snapshot:
                screening_sources.append({
                    "source_name": "Stored company screening calculation", "record_id": snapshot.id,
                    "instrument_id": instrument.id, "data_cutoff": snapshot.as_of_date,
                    "computed_at": snapshot.computed_at,
                    "calculation_method": "within_sector_observed_growth_margin_liquidity",
                })
        data["screening_coverage"] = {
            "returned_instruments": len(rows), "with_snapshot": len(snapshots),
            "missing_snapshot": len(rows) - len(snapshots), "fields": fields,
            "units": "dimensionless ratios; sector_percentile is within-sector only",
        }
    returned = len(rows)
    remaining = max(0, total - offset - returned)
    return tool_result(
        "ok" if rows else "missing",
        data,
        sources=screening_sources + list(
            {
                company.psx_url: {
                    "source_name": "PSX symbol universe",
                    "source_url": company.psx_url,
                }
                for _, company in rows
                if company.psx_url
            }.values()
        ),
        returned=returned,
        remaining=remaining,
        continuation=str(offset + returned) if remaining else None,
    )


def register_market_tools(registry: ToolRegistry) -> None:
    registry.register(ToolDefinition(
        "market.overview", "1.0",
        "Database market snapshot, gainers, losers, volume leaders and sectors. Select only needed sections; each reports dates and stored coverage.",
        MarketOverviewInput, "market:read", True, False, 10, "low", _overview,
    ))
    registry.register(
        ToolDefinition(
            "market.freshness",
            "1.0",
            "Current structured market-data freshness and provider status",
            EmptyInput,
            "market:read",
            True,
            False,
            5,
            "low",
            _freshness,
        )
    )
    registry.register(
        ToolDefinition(
            "market.series",
            "1.0",
            "Canonical OHLCV history with observation provenance. Returns at most 260 latest observations; use the continuation date as end to request older history.",
            MarketSeriesInput,
            "market:read",
            True,
            False,
            10,
            "medium",
            _series,
        )
    )
    registry.register(
        ToolDefinition(
            "macro.releases",
            "1.0",
            "Observed macro series and effective-dated releases",
            MacroInput,
            "market:read",
            True,
            False,
            10,
            "medium",
            _macro,
        )
    )
    registry.register(
        ToolDefinition(
            "market.universe",
            "1.0",
            "Paginated active PSX instruments with authoritative sectors; optional stored screening fields batched for the page. Missing values remain explicit; identity-only by default.",
            MarketUniverseInput,
            "market:read",
            True,
            False,
            10,
            "low",
            _universe,
        )
    )
