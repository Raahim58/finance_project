from datetime import date, timedelta

from pydantic import BaseModel, Field

from app.services.market_service import get_market_freshness
from app.services.research_service import list_macro_series, macro_releases, market_series
from app.models.market import Company
from app.models.workstation import Instrument
from app.tools.registry import ToolDefinition, ToolRegistry, tool_result
from sqlalchemy import func, select


class EmptyInput(BaseModel):
    pass


class MarketSeriesInput(BaseModel):
    instrument_id: str
    start: date | None = None
    end: date | None = None
    limit: int = Field(default=260, ge=2, le=260)


class MacroInput(BaseModel):
    series_id: str | None = None


class MarketUniverseInput(BaseModel):
    sector: str | None = Field(default=None, max_length=120)
    cursor: str | None = Field(default=None, pattern=r"^[0-9]+$")
    limit: int = Field(default=50, ge=1, le=100)


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
    returned = len(rows)
    remaining = max(0, total - offset - returned)
    return tool_result(
        "ok" if rows else "missing",
        data,
        sources=list(
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
            "Paginated active PSX instruments with authoritative sector classifications",
            MarketUniverseInput,
            "market:read",
            True,
            False,
            10,
            "low",
            _universe,
        )
    )
