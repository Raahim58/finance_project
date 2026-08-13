from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.market import MarketPrice
from app.models.workstation import (
    DataSource,
    Event,
    EventEntityLink,
    EventSource,
    FinancialFact,
    IngestionRun,
    Instrument,
    MacroObservation,
    MacroSeries,
)


@dataclass(frozen=True)
class SourceDefinition:
    source: str
    providers: tuple[str, ...]
    freshness_sla_minutes: int | None


SOURCE_DEFINITIONS = (
    SourceDefinition("DPS", ("dps", "auto", "psxdata", "yahoo", "market_prices"), 4_320),
    SourceDefinition("Mettis", ("mettis",), 480),
    SourceDefinition("PSX Financial Reports", ("psx_financials",), 10_080),
    SourceDefinition("SBP", ("sbp",), 4_320),
    SourceDefinition("PBS", ("pbs",), 50_400),
    SourceDefinition("World Bank", ("world_bank",), 50_400),
    SourceDefinition("SCSTrade", ("scstrade",), 10_080),
    # Phase 1 intentionally has no real announcements provider.
    SourceDefinition("PSX Announcements", ("psx_announcements",), None),
)

SUCCESS_STATUSES = {"success", "completed", "partial"}


def _as_utc_datetime(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.combine(value, datetime.min.time(), tzinfo=UTC)


def _configured_sla(db: Session, definition: SourceDefinition) -> int | None:
    names = {
        "DPS": ("DPS",),
        "Mettis": ("Mettis Global",),
        "PSX Financial Reports": ("PSX Financials",),
        "SBP": ("SBP",),
        "PBS": ("PBS",),
        "World Bank": ("WORLD_BANK", "World Bank"),
        "SCSTrade": ("SCSTrade",),
    }.get(definition.source, ())
    if not names:
        return definition.freshness_sla_minutes
    configured = db.scalar(
        select(DataSource.freshness_sla_minutes)
        .where(DataSource.name.in_(names), DataSource.freshness_sla_minutes.is_not(None))
        .order_by(DataSource.priority)
        .limit(1)
    )
    return int(configured) if configured is not None else definition.freshness_sla_minutes


def _latest_data_at(db: Session, source_name: str) -> datetime | None:
    if source_name == "DPS":
        value = db.scalar(select(func.max(MarketPrice.trade_date)).where(MarketPrice.source != "mock"))
    elif source_name == "SCSTrade":
        value = db.scalar(select(func.max(MarketPrice.trade_date)).where(MarketPrice.source == "scstrade"))
    elif source_name == "Mettis":
        value = db.scalar(
            select(func.max(Event.occurred_at))
            .join(EventSource, EventSource.event_id == Event.id)
            .where(EventSource.source_name == "Mettis Global")
        )
    elif source_name == "PSX Financial Reports":
        value = db.scalar(
            select(func.max(Document.published_date)).where(
                Document.source_name == "PSX Financials",
                or_(Document.source_url.is_(None), ~Document.source_url.startswith("demo://")),
            )
        )
    elif source_name in {"SBP", "PBS", "World Bank"}:
        names = {
            "SBP": ("SBP",),
            "PBS": ("PBS",),
            "World Bank": ("WORLD_BANK", "World Bank"),
        }[source_name]
        value = db.scalar(
            select(func.max(MacroObservation.effective_date))
            .join(MacroSeries, MacroSeries.id == MacroObservation.series_id)
            .join(DataSource, DataSource.id == MacroSeries.source_id)
            .where(DataSource.name.in_(names), MacroObservation.is_selected.is_(True))
        )
    else:
        value = None
    return _as_utc_datetime(value)


def source_health(db: Session, *, now: datetime | None = None) -> dict[str, object]:
    current = now or datetime.now(UTC)
    sources: list[dict[str, object]] = []
    for definition in SOURCE_DEFINITIONS:
        runs = list(
            db.scalars(
                select(IngestionRun)
                .where(IngestionRun.provider.in_(definition.providers), IngestionRun.job_key.like("refresh:%"))
                .order_by(IngestionRun.started_at.desc())
            )
        )
        latest = runs[0] if runs else None
        successful = next((run for run in runs if run.status in SUCCESS_STATUSES), None)
        latest_data_at = _latest_data_at(db, definition.source)
        sla = _configured_sla(db, definition)
        if latest is None:
            status = "never_run"
        elif latest.status == "failed":
            status = "failed"
        elif latest.status == "partial":
            status = "partial"
        elif latest_data_at is None:
            status = "stale"
        elif sla is not None and current - latest_data_at > timedelta(minutes=sla):
            status = "stale"
        else:
            status = "healthy"
        sources.append(
            {
                "source": definition.source,
                "status": status,
                "last_attempt": latest.started_at if latest else None,
                "last_success": (successful.finished_at or successful.started_at) if successful else None,
                "latest_data_at": latest_data_at,
                "attempted": latest.attempted_count if latest else 0,
                "accepted": latest.accepted_count if latest else 0,
                "updated": latest.updated_count if latest else 0,
                "rejected": latest.rejected_count if latest else 0,
                "error": latest.error_message if latest else None,
                "freshness_sla_minutes": sla,
            }
        )
    return {"sources": sources}


def _observed_document_filter(symbol: str):
    return (
        func.upper(Document.symbol) == symbol,
        or_(Document.source_url.is_(None), ~Document.source_url.startswith("demo://")),
        ~func.lower(Document.source_name).contains("demo"),
    )


def company_completeness(db: Session, symbol: str) -> dict[str, object]:
    normalized = symbol.strip().upper()
    instrument = db.scalar(select(Instrument).where(func.upper(Instrument.symbol) == normalized))
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found")

    price_count, latest_price = db.execute(
        select(func.count(MarketPrice.id), func.max(MarketPrice.trade_date)).where(
            func.upper(MarketPrice.symbol) == normalized,
            MarketPrice.source != "mock",
        )
    ).one()
    fact_count, latest_period = db.execute(
        select(func.count(FinancialFact.id), func.max(FinancialFact.period_end))
        .join(Document, Document.id == FinancialFact.document_id)
        .where(
            FinancialFact.instrument_id == instrument.id,
            Document.source_url.is_not(None),
            ~func.lower(Document.source_url).like("demo://%"),
            ~func.lower(Document.source_name).contains("demo"),
            Document.document_type != "synthetic_demo_facts",
        )
    ).one()
    report_count, latest_report = db.execute(
        select(func.count(Document.id), func.max(Document.published_date)).where(
            *_observed_document_filter(normalized),
            Document.document_type.in_(("annual_report", "quarterly_report", "half_year_report", "company_report")),
        )
    ).one()

    def event_coverage(event_type: str) -> tuple[int, datetime | None]:
        return db.execute(
            select(func.count(Event.id), func.max(Event.occurred_at))
            .join(EventEntityLink, EventEntityLink.event_id == Event.id)
            .join(EventSource, EventSource.event_id == Event.id)
            .where(
                Event.event_type == event_type,
                EventEntityLink.entity_type == "instrument",
                func.upper(EventEntityLink.entity_key) == normalized,
                ~func.lower(EventSource.source_name).contains("demo"),
                ~EventSource.source_url.startswith("demo://"),
            )
        ).one()

    announcement_count, latest_announcement = event_coverage("announcement")
    news_count, latest_news = event_coverage("news")

    def category(count: int, latest: date | datetime | None, reason: str) -> dict[str, object]:
        return {
            "available": count > 0,
            "count": count,
            "latest_date": _as_utc_datetime(latest),
            "reason": None if count else reason,
        }

    return {
        "symbol": normalized,
        "price": {
            **category(price_count, latest_price, "No observed live price data is stored for this security."),
            "observations": price_count,
        },
        "fundamentals": {
            **category(fact_count, latest_period, "No observed normalized financial facts are stored for this security."),
            "fact_count": fact_count,
            "latest_period": _as_utc_datetime(latest_period),
        },
        "reports": category(report_count, latest_report, "No observed company reports are stored for this security."),
        "announcements": category(announcement_count, latest_announcement, "No real announcements provider is configured in Phase 1."),
        "news": category(news_count, latest_news, "No sourced news is linked to this security."),
    }
