"""Canonical macro catalog persistence, reconciliation, and provider fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion.macro_catalog import MACRO_SERIES, MACRO_SERIES_BY_KEY, MacroSeriesSpec
from app.models.workstation import (
    DataQualityIssue,
    DataSource,
    MacroObservation,
    MacroSeries,
    MacroSeriesProvider,
)
from app.providers.macro.series import ProviderResult, fetch_macro_provider
from app.services.ingestion_persistence import source, store_artifact


@dataclass(frozen=True)
class MacroRefreshResult:
    series_key: str
    providers_attempted: int
    providers_succeeded: int
    observations_written: int
    latest_observation: date | None
    diagnostics: tuple[dict[str, object], ...]


def _confidence(authority: str) -> Decimal:
    return {
        "national_official": Decimal("1.00000"),
        "official_supranational": Decimal("0.98000"),
        "official_international": Decimal("0.95000"),
        "official_aggregator": Decimal("0.90000"),
        "reputable_mirror": Decimal("0.70000"),
        "manual": Decimal("0.50000"),
    }.get(authority, Decimal("0.60000"))


def ensure_macro_catalog(db: Session) -> tuple[int, int]:
    """Upsert canonical series and ordered provider contracts without fetching."""

    series_count = provider_count = 0
    for spec in MACRO_SERIES:
        providers: list[tuple[object, DataSource]] = []
        for provider in sorted(spec.providers, key=lambda item: item.priority):
            data_source = source(
                db,
                provider.source_name,
                "macro",
                provider.base_url,
                provider.priority,
                1440 if spec.frequency in {"daily", "auction"} else 10080,
                f"{provider.authority} macro provider via {provider.retrieval_method}.",
            )
            providers.append((provider, data_source))
        primary_source = providers[0][1]
        series = db.scalar(select(MacroSeries).where(MacroSeries.key == spec.key))
        metadata = {
            "canonical": True,
            "dimension": spec.dimension,
            "provider_ladder": [provider.key for provider, _ in providers],
            "selection_policy": "lowest_priority_success_with_conflict_diagnostic",
        }
        if series is None:
            series = MacroSeries(
                key=spec.key,
                name=spec.name,
                unit=spec.unit,
                frequency=spec.frequency,
                source_id=primary_source.id,
                metadata_json=json.dumps(metadata, sort_keys=True),
            )
            db.add(series)
            db.flush()
            series_count += 1
        else:
            series.name = spec.name
            series.unit = spec.unit
            series.frequency = spec.frequency
            series.source_id = primary_source.id
            series.metadata_json = json.dumps(metadata, sort_keys=True)
        for provider, data_source in providers:
            row = db.scalar(
                select(MacroSeriesProvider).where(
                    MacroSeriesProvider.series_id == series.id,
                    MacroSeriesProvider.provider_key == provider.key,
                )
            )
            provider_metadata = {"kind": provider.kind, "params": provider.params}
            if row is None:
                row = MacroSeriesProvider(
                    series_id=series.id,
                    data_source_id=data_source.id,
                    provider_key=provider.key,
                    source_series_id=provider.source_series_id,
                    priority=provider.priority,
                    authority=provider.authority,
                    retrieval_method=provider.retrieval_method,
                    enabled=provider.enabled,
                    metadata_json=json.dumps(provider_metadata, sort_keys=True),
                )
                db.add(row)
                provider_count += 1
            else:
                row.data_source_id = data_source.id
                row.source_series_id = provider.source_series_id
                row.priority = provider.priority
                row.authority = provider.authority
                row.retrieval_method = provider.retrieval_method
                row.enabled = provider.enabled
                row.metadata_json = json.dumps(provider_metadata, sort_keys=True)
    db.flush()
    return series_count, provider_count


def _reconcile_date(db: Session, series: MacroSeries, effective_date: date) -> None:
    providers = {
        row.id: row
        for row in db.scalars(
            select(MacroSeriesProvider).where(MacroSeriesProvider.series_id == series.id)
        )
    }
    rows = list(
        db.scalars(
            select(MacroObservation)
            .where(
                MacroObservation.series_id == series.id,
                MacroObservation.effective_date == effective_date,
                MacroObservation.provider_id.is_not(None),
            )
            .order_by(MacroObservation.release_at.desc(), MacroObservation.id.desc())
        )
    )
    latest_by_provider: dict[str, MacroObservation] = {}
    for row in rows:
        if row.provider_id and row.provider_id not in latest_by_provider:
            latest_by_provider[row.provider_id] = row
        row.is_selected = False
    candidates = [
        (providers[provider_id], observation)
        for provider_id, observation in latest_by_provider.items()
        if provider_id in providers
    ]
    if not candidates:
        return
    candidates.sort(key=lambda item: (item[0].priority, item[0].provider_key))
    selected_provider, selected = candidates[0]
    selected.is_selected = True
    values = {str(observation.value) for _, observation in candidates}
    reason = {
        "selected_provider": selected_provider.provider_key,
        "selected_priority": selected_provider.priority,
        "providers_observed": [provider.provider_key for provider, _ in candidates],
        "conflict": len(values) > 1,
    }
    selected.selection_reason = json.dumps(reason, sort_keys=True)
    if len(values) > 1:
        exists = db.scalar(
            select(DataQualityIssue.id).where(
                DataQualityIssue.observation_id == selected.id,
                DataQualityIssue.rule == "macro_provider_disagreement",
            )
        )
        if not exists:
            db.add(
                DataQualityIssue(
                    artifact_id=selected.artifact_id,
                    observation_id=selected.id,
                    rule="macro_provider_disagreement",
                    severity="warning",
                    details_json=json.dumps(
                        {
                            "series_key": series.key,
                            "effective_date": effective_date.isoformat(),
                            "values": {
                                provider.provider_key: str(observation.value)
                                for provider, observation in candidates
                            },
                        },
                        sort_keys=True,
                    ),
                    selection_status="open",
                )
            )


def persist_provider_result(
    db: Session,
    spec: MacroSeriesSpec,
    result: ProviderResult,
) -> int:
    series = db.scalar(select(MacroSeries).where(MacroSeries.key == spec.key))
    if series is None:
        raise RuntimeError(f"Canonical macro series {spec.key} is not registered")
    provider = db.scalar(
        select(MacroSeriesProvider).where(
            MacroSeriesProvider.series_id == series.id,
            MacroSeriesProvider.provider_key == result.provider_key,
        )
    )
    if provider is None:
        raise RuntimeError(f"Macro provider {result.provider_key} is not registered")
    data_source = db.get(DataSource, provider.data_source_id)
    if data_source is None:
        raise RuntimeError("Macro provider data source is missing")
    artifact = store_artifact(
        db,
        data_source,
        result.content,
        url=result.url,
        method="GET",
        parser_version=result.parser_version,
        content_type=result.content_type or "application/octet-stream",
    )
    written = 0
    touched: set[date] = set()
    for item in result.observations:
        exists = db.scalar(
            select(MacroObservation.id).where(
                MacroObservation.series_id == series.id,
                MacroObservation.provider_id == provider.id,
                MacroObservation.effective_date == item.effective_date,
                MacroObservation.value == item.value,
            )
        )
        if exists:
            touched.add(item.effective_date)
            continue
        revision = (
            db.scalar(
                select(func.coalesce(func.max(MacroObservation.revision), 0)).where(
                    MacroObservation.series_id == series.id,
                    MacroObservation.effective_date == item.effective_date,
                )
            )
            or 0
        ) + 1
        row = MacroObservation(
            series_id=series.id,
            effective_date=item.effective_date,
            release_at=result.retrieved_at,
            value=item.value,
            revision=revision,
            artifact_id=artifact.id,
            provider_id=provider.id,
            source_series_id=result.source_series_id,
            retrieved_at=result.retrieved_at,
            vintage_date=item.vintage_date,
            authority=provider.authority,
            confidence=_confidence(provider.authority),
            is_selected=False,
        )
        db.add(row)
        db.flush()
        touched.add(item.effective_date)
        written += 1
    for effective_date in touched:
        _reconcile_date(db, series, effective_date)
    db.flush()
    return written


def refresh_macro_series(
    db: Session,
    series_key: str,
    *,
    start: date,
    end: date,
) -> MacroRefreshResult:
    spec = MACRO_SERIES_BY_KEY.get(series_key)
    if spec is None:
        raise ValueError(f"Unknown canonical macro series {series_key!r}")
    ensure_macro_catalog(db)
    db.commit()
    diagnostics: list[dict[str, object]] = []
    attempted = succeeded = written = 0
    latest: date | None = None
    for provider in sorted(spec.providers, key=lambda item: item.priority):
        if not provider.enabled:
            diagnostics.append(
                {
                    "provider": provider.key,
                    "status": "disabled",
                    "reason": provider.params.get("reason", "disabled by runtime configuration"),
                }
            )
            continue
        attempted += 1
        try:
            result = fetch_macro_provider(provider, start, end)
            count = persist_provider_result(db, spec, result)
            db.commit()
            succeeded += 1
            written += count
            provider_latest = max(item.effective_date for item in result.observations)
            latest = max(latest or provider_latest, provider_latest)
            diagnostics.append(
                {
                    "provider": provider.key,
                    "status": "success",
                    "observations": len(result.observations),
                    "written": count,
                    "latest": provider_latest.isoformat(),
                }
            )
        except Exception as exc:
            db.rollback()
            diagnostics.append(
                {
                    "provider": provider.key,
                    "status": "failed",
                    "error_class": type(exc).__name__,
                    "error": str(exc)[:500],
                }
            )
    if not succeeded:
        raise RuntimeError(json.dumps({"series": series_key, "providers": diagnostics}, sort_keys=True))
    return MacroRefreshResult(series_key, attempted, succeeded, written, latest, tuple(diagnostics))
