from dataclasses import dataclass
import json
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.evidence import DiscoveryCandidate, EvidenceSourceConfig, EvidenceSourceState
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
    MacroSeriesProvider,
    StandardizedFinancialFact,
)
from app.services.company_event_service import sourced_company_events


@dataclass(frozen=True)
class SourceDefinition:
    source: str
    providers: tuple[str, ...]
    freshness_sla_minutes: int | None


SOURCE_DEFINITIONS = (
    SourceDefinition("DPS", ("dps", "auto"), 4_320),
    SourceDefinition("Mettis", ("mettis",), 480),
    SourceDefinition("PSX Financial Reports", ("psx_financials",), 10_080),
    SourceDefinition("SBP", ("sbp",), 4_320),
    SourceDefinition("PBS", ("pbs",), 50_400),
    SourceDefinition("World Bank", ("world_bank",), 50_400),
    SourceDefinition("Canonical Macro", ("provider_ladder",), 10_080),
    SourceDefinition("SCSTrade", ("scstrade",), 10_080),
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
        "Canonical Macro": (),
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
        value = db.scalar(select(func.max(MarketPrice.trade_date)).where(MarketPrice.source == "dps"))
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
    elif source_name == "Canonical Macro":
        value = db.scalar(
            select(func.max(MacroObservation.effective_date)).where(
                MacroObservation.is_selected.is_(True)
            )
        )
    elif source_name in {"SBP", "PBS", "World Bank"}:
        names = {
            "SBP": ("SBP", "State Bank of Pakistan"),
            "PBS": ("PBS", "Pakistan Bureau of Statistics"),
            "World Bank": (
                "WORLD_BANK",
                "World Bank",
                "World Bank Indicators API",
                "World Bank Commodity Markets",
            ),
        }[source_name]
        value = db.scalar(
            select(func.max(MacroObservation.effective_date))
            .join(MacroSeriesProvider, MacroSeriesProvider.id == MacroObservation.provider_id)
            .join(DataSource, DataSource.id == MacroSeriesProvider.data_source_id)
            .where(DataSource.name.in_(names), MacroObservation.is_selected.is_(True))
        )
    else:
        value = None
    return _as_utc_datetime(value)


def source_health(db: Session, *, now: datetime | None = None) -> dict[str, object]:
    current = now or datetime.now(UTC)
    sources: list[dict[str, object]] = []
    for definition in SOURCE_DEFINITIONS:
        run_filter = (
            IngestionRun.job_key == "macro-series-refresh"
            if definition.source == "Canonical Macro"
            else IngestionRun.job_key.like("refresh:%")
        )
        runs = list(
            db.scalars(
                select(IngestionRun)
                .where(IngestionRun.provider.in_(definition.providers), run_filter)
                .order_by(IngestionRun.started_at.desc())
            )
        )
        if definition.source == "DPS":
            runs = [
                run for run in runs
                if run.provider == "dps"
                or (
                    run.provider == "auto"
                    and json.loads(run.diagnostics_json or "{}").get("used_provider") == "dps"
                )
            ]
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
    positions = {row["source"]: index for index, row in enumerate(sources)}
    evidence_rows = db.execute(
        select(EvidenceSourceConfig, EvidenceSourceState, DataSource)
        .join(EvidenceSourceState, EvidenceSourceState.source_config_id == EvidenceSourceConfig.id)
        .join(DataSource, DataSource.id == EvidenceSourceConfig.data_source_id)
        .where(DataSource.enabled.is_(True))
    ).all()
    for config, state, data_source in evidence_rows:
        status_counts = dict(
            db.execute(
                select(DiscoveryCandidate.status, func.count())
                .where(DiscoveryCandidate.source_config_id == config.id)
                .group_by(DiscoveryCandidate.status)
            ).all()
        )
        attempted = sum(status_counts.values())
        accepted = status_counts.get("selected", 0) + status_counts.get("duplicate", 0)
        rejected = status_counts.get("rejected", 0) + status_counts.get("failed", 0)
        latest_data_at = _as_utc_datetime(
            db.scalar(
                select(func.max(func.coalesce(EventSource.published_at, DiscoveryCandidate.selected_at)))
                .join(DiscoveryCandidate, DiscoveryCandidate.id == EventSource.candidate_id)
                .where(DiscoveryCandidate.source_config_id == config.id)
            )
        )
        sla = data_source.freshness_sla_minutes
        diagnostics = json.loads(state.diagnostics_json or "{}")
        if state.last_attempted_at is None:
            status = "never_run"
        elif state.consecutive_failures:
            status = "failed"
        elif diagnostics.get("failed"):
            status = "partial"
        elif state.last_success_at is None:
            status = "stale"
        elif sla is not None and current - _as_utc_datetime(state.last_success_at) > timedelta(minutes=sla):
            status = "stale"
        else:
            status = "healthy"
        display_name = {
            "mettis": "Mettis",
            "psx_announcements": "PSX Announcements",
        }.get(config.source_key, data_source.name)
        evidence_health = {
            "source": display_name,
            "status": status,
            "last_attempt": state.last_attempted_at,
            "last_success": state.last_success_at,
            "latest_data_at": latest_data_at,
            "attempted": attempted,
            "accepted": accepted,
            "updated": 0,
            "rejected": rejected,
            "error": state.last_error_message,
            "freshness_sla_minutes": sla,
        }
        if display_name in positions:
            sources[positions[display_name]] = evidence_health
        else:
            positions[display_name] = len(sources)
            sources.append(evidence_health)
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
    standardized_count, latest_standardized_period = db.execute(
        select(
            func.count(StandardizedFinancialFact.id),
            func.max(StandardizedFinancialFact.period_end),
        ).where(
            StandardizedFinancialFact.instrument_id == instrument.id,
            StandardizedFinancialFact.quality_status == "observed",
        )
    ).one()
    fact_count = int(fact_count or 0) + int(standardized_count or 0)
    latest_period = max(
        (value for value in (latest_period, latest_standardized_period) if value is not None),
        default=None,
    )
    report_count, latest_report = db.execute(
        select(func.count(Document.id), func.max(Document.published_date)).where(
            *_observed_document_filter(normalized),
            Document.document_type.in_(("annual_report", "quarterly_report", "half_year_report", "company_report")),
        )
    ).one()

    company_events = sourced_company_events(db, instrument)

    def event_coverage(event_type: str) -> tuple[int, datetime | None]:
        matching = [row.event for row in company_events if row.event.event_type == event_type]
        return len(matching), max((row.occurred_at for row in matching), default=None)

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
        "announcements": category(announcement_count, latest_announcement, "No observed PSX announcements are linked to this security."),
        "news": category(news_count, latest_news, "No sourced news is linked to this security."),
    }
