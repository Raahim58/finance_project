from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.market import MarketPrice
from app.models.workstation import (
    DataQualityIssue,
    DataSource,
    Instrument,
    MarketObservation,
    SourceArtifact,
)
from app.services.market_numbers import safe_decimal, safe_int


SOURCE_PRIORITIES = {"dps": 10, "vendor": 20, "psxdata": 30, "scstrade": 40, "yahoo": 50, "mock": 1000}
SYNTHETIC_SOURCE_NAMES = {"mock", "deterministic demo seed", "deterministic demo macro"}


def synthetic_market_data_allowed() -> bool:
    """Return true only for the explicit deterministic market fixture mode."""
    return settings.is_synthetic_environment


def _is_synthetic_source(source: DataSource | None, artifact: SourceArtifact | None) -> bool:
    name = (source.name if source else "").strip().lower()
    url = (artifact.source_url if artifact else "").strip().lower()
    return name in SYNTHETIC_SOURCE_NAMES or url.startswith(("demo://", "normalized://mock/"))


@dataclass(frozen=True, slots=True)
class CanonicalPrice:
    instrument_id: str | None
    symbol: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    previous_close: Decimal
    volume: int
    market_cap: Decimal | None
    source: str
    source_url: str | None
    artifact_id: str | None
    artifact_sha256: str | None
    observed_at: datetime | None
    adjustment_state: str
    quality_status: str

    @property
    def change(self) -> Decimal:
        return self.close - self.previous_close

    @property
    def change_percent(self) -> Decimal:
        return (self.change / self.previous_close * Decimal("100")) if self.previous_close else Decimal("0")

    @property
    def value(self) -> Decimal:
        return self.close * Decimal(self.volume)


def validate_observed_price(row) -> tuple[dict[str, Decimal | int | None] | None, list[dict[str, object]]]:
    fields = {
        "open": safe_decimal(getattr(row, "open", None)),
        "high": safe_decimal(getattr(row, "high", None)),
        "low": safe_decimal(getattr(row, "low", None)),
        "close": safe_decimal(getattr(row, "close", None)),
        "previous_close": safe_decimal(getattr(row, "previous_close", None)),
    }
    volume = safe_int(getattr(row, "volume", None))
    issues: list[dict[str, object]] = []
    missing = [name for name, value in fields.items() if value is None]
    if missing:
        issues.append({"rule": "required_ohlc_missing", "severity": "error", "fields": missing})
    if volume is None:
        issues.append({"rule": "volume_missing", "severity": "error"})
    if issues:
        return None, issues
    typed = {name: Decimal(value) for name, value in fields.items() if value is not None}
    if min(typed.values()) <= 0:
        issues.append({"rule": "non_positive_price", "severity": "error"})
    if typed["high"] < max(typed["open"], typed["close"], typed["low"]):
        issues.append({"rule": "invalid_ohlc_high", "severity": "error"})
    if typed["low"] > min(typed["open"], typed["close"], typed["high"]):
        issues.append({"rule": "invalid_ohlc_low", "severity": "error"})
    if int(volume) < 0:
        issues.append({"rule": "negative_volume", "severity": "error"})
    if issues:
        return None, issues
    change = typed["close"] - typed["previous_close"]
    return {
        **typed,
        "change": change,
        "change_percent": (change / typed["previous_close"] * Decimal("100")) if typed["previous_close"] else Decimal("0"),
        "volume": int(volume),
        "value": typed["close"] * Decimal(int(volume)),
        "market_cap": safe_decimal(getattr(row, "market_cap", None)),
    }, []


def _source(db: Session, source_name: str) -> DataSource:
    normalized = source_name.lower()
    display = "PSX DPS" if normalized == "dps" else normalized.upper()
    row = db.scalar(select(DataSource).where(func.lower(DataSource.name) == display.lower()))
    if row is None:
        row = DataSource(
            name=display,
            source_type="market",
            priority=SOURCE_PRIORITIES.get(normalized, 100),
            enabled=True,
            freshness_sla_minutes=1440,
            use_notes="Canonical market observation source.",
        )
        db.add(row)
        db.flush()
    return row


def persist_normalized_observations(db: Session, rows: Iterable, source_name: str) -> tuple[int, int]:
    """Persist normalized provider output when a raw transport artifact is unavailable.

    The artifact explicitly records that it is normalized, not a raw-response substitute.
    """
    rows = list(rows)
    payload = [
        {
            "symbol": str(row.symbol).upper(),
            "trade_date": row.trade_date.isoformat(),
            "open": str(row.open),
            "high": str(row.high),
            "low": str(row.low),
            "close": str(row.close),
            "previous_close": str(row.previous_close),
            "volume": row.volume,
            "market_cap": None if getattr(row, "market_cap", None) is None else str(row.market_cap),
        }
        for row in rows
    ]
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = sha256(content).hexdigest()
    data_source = _source(db, source_name)
    artifact = db.scalar(
        select(SourceArtifact).where(
            SourceArtifact.data_source_id == data_source.id,
            SourceArtifact.request_fingerprint == digest,
            SourceArtifact.sha256 == digest,
        )
    )
    if artifact is None:
        artifact = SourceArtifact(
            data_source_id=data_source.id,
            source_url=f"normalized://{source_name}/market-prices",
            http_method="NORMALIZE",
            request_fingerprint=digest,
            retrieved_at=datetime.now(UTC),
            sha256=digest,
            content_type="application/json",
            parser_version=f"{source_name}-normalized-v1",
            status="normalized",
            response_metadata_json=json.dumps({"representation": "normalized_provider_output", "rows": len(rows)}),
        )
        db.add(artifact)
        db.flush()

    accepted = rejected = 0
    touched: set[tuple[str, datetime]] = set()
    for row in rows:
        cleaned, issues = validate_observed_price(row)
        if issues:
            rejected += 1
            for issue in issues:
                db.add(
                    DataQualityIssue(
                        artifact_id=artifact.id,
                        rule=str(issue["rule"]),
                        severity=str(issue["severity"]),
                        details_json=json.dumps({"symbol": row.symbol, "trade_date": row.trade_date.isoformat(), **issue}),
                        selection_status="rejected",
                    )
                )
            continue
        instrument = db.scalar(select(Instrument).where(func.upper(Instrument.symbol) == row.symbol.upper()))
        if instrument is None:
            rejected += 1
            db.add(DataQualityIssue(artifact_id=artifact.id, rule="instrument_unresolved", severity="error", details_json=json.dumps({"symbol": row.symbol}), selection_status="rejected"))
            continue
        effective_at = datetime.combine(row.trade_date, datetime.min.time(), tzinfo=ZoneInfo("Asia/Karachi"))
        touched.add((instrument.id, effective_at))
        existing = db.scalar(
            select(MarketObservation).where(
                MarketObservation.instrument_id == instrument.id,
                MarketObservation.effective_at == effective_at,
                MarketObservation.frequency == "daily",
                MarketObservation.artifact_id == artifact.id,
            )
        )
        if existing is None:
            values = {key: str(value) if isinstance(value, Decimal) else value for key, value in cleaned.items()}
            db.add(
                MarketObservation(
                    instrument_id=instrument.id,
                    effective_at=effective_at,
                    frequency="daily",
                    values_json=json.dumps(values, sort_keys=True),
                    currency="PKR",
                    unit="price",
                    adjustment_state="unadjusted",
                    artifact_id=artifact.id,
                    is_selected=False,
                )
            )
            accepted += 1
    db.flush()
    for instrument_id, effective_at in touched:
        reconcile_market_observations(db, instrument_id=instrument_id, effective_at=effective_at)
    return accepted, rejected


def reconcile_market_observations(
    db: Session,
    instrument_id: str | None = None,
    effective_at: datetime | None = None,
) -> int:
    statement = select(MarketObservation)
    if instrument_id:
        statement = statement.where(MarketObservation.instrument_id == instrument_id)
    if effective_at:
        statement = statement.where(MarketObservation.effective_at == effective_at)
    observations = list(db.scalars(statement))
    groups: dict[tuple[str | None, str | None, datetime, str], list[MarketObservation]] = {}
    for observation in observations:
        groups.setdefault((observation.instrument_id, observation.series_key, observation.effective_at, observation.frequency), []).append(observation)

    selected_count = 0
    for candidates in groups.values():
        ranked = []
        for candidate in candidates:
            artifact = db.get(SourceArtifact, candidate.artifact_id)
            source = db.get(DataSource, artifact.data_source_id) if artifact else None
            rejected = db.scalar(
                select(func.count(DataQualityIssue.id)).where(
                    DataQualityIssue.observation_id == candidate.id,
                    DataQualityIssue.selection_status == "rejected",
                )
            ) or 0
            ranked.append(((1 if rejected else 0, 1 if _is_synthetic_source(source, artifact) else 0, source.priority if source else 10_000, -(artifact.retrieved_at.timestamp() if artifact else 0)), candidate, artifact, source))
        ranked.sort(key=lambda item: item[0])
        winner = ranked[0][1]
        distinct_values = {candidate.values_json for _, candidate, _, _ in ranked}
        for _, candidate, artifact, source in ranked:
            candidate.is_selected = candidate.id == winner.id
            if candidate.is_selected:
                selected_count += 1
            elif len(distinct_values) > 1 and not db.scalar(
                select(DataQualityIssue.id).where(
                    DataQualityIssue.observation_id == candidate.id,
                    DataQualityIssue.rule == "source_conflict_not_selected",
                )
            ):
                db.add(
                    DataQualityIssue(
                        artifact_id=artifact.id if artifact else None,
                        observation_id=candidate.id,
                        rule="source_conflict_not_selected",
                        severity="warning",
                        details_json=json.dumps({"selected_observation_id": winner.id, "source": source.name if source else None}),
                        resolution="Canonical source-priority reconciliation",
                        selection_status="not_selected",
                    )
                )
    db.flush()
    return selected_count


def _from_observation_parts(
    observation: MarketObservation,
    artifact: SourceArtifact | None,
    source: DataSource | None,
    symbol: str,
) -> CanonicalPrice:
    values = json.loads(observation.values_json)
    return CanonicalPrice(
        instrument_id=observation.instrument_id,
        symbol=symbol,
        trade_date=observation.effective_at.date(),
        open=Decimal(str(values["open"])),
        high=Decimal(str(values["high"])),
        low=Decimal(str(values["low"])),
        close=Decimal(str(values["close"])),
        previous_close=Decimal(str(values.get("previous_close", values["close"]))),
        volume=int(values.get("volume") or 0),
        market_cap=Decimal(str(values["market_cap"])) if values.get("market_cap") is not None else None,
        source=(source.name if source else "unknown").lower().replace("psx ", ""),
        source_url=artifact.source_url if artifact else None,
        artifact_id=artifact.id if artifact else None,
        artifact_sha256=artifact.sha256 if artifact else None,
        observed_at=artifact.retrieved_at if artifact else None,
        adjustment_state=observation.adjustment_state,
        quality_status="selected",
    )


def _from_observation(db: Session, observation: MarketObservation, symbol: str) -> CanonicalPrice:
    artifact = db.get(SourceArtifact, observation.artifact_id)
    source = db.get(DataSource, artifact.data_source_id) if artifact else None
    return _from_observation_parts(observation, artifact, source, symbol)


def price_series(
    db: Session,
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    *,
    allow_legacy_fallback: bool = True,
) -> list[CanonicalPrice]:
    normalized_symbol = symbol.strip().upper()
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == normalized_symbol))
    if instrument:
        statement = (
            select(MarketObservation, SourceArtifact, DataSource)
            .join(SourceArtifact, SourceArtifact.id == MarketObservation.artifact_id)
            .join(DataSource, DataSource.id == SourceArtifact.data_source_id)
            .where(
            MarketObservation.instrument_id == instrument.id,
            MarketObservation.is_selected.is_(True),
            MarketObservation.frequency == "daily",
            )
        )
        if not synthetic_market_data_allowed():
            statement = statement.where(
                ~func.lower(DataSource.name).in_(SYNTHETIC_SOURCE_NAMES),
                ~func.lower(SourceArtifact.source_url).like("demo://%"),
                ~func.lower(SourceArtifact.source_url).like("normalized://mock/%"),
            )
        if start:
            statement = statement.where(MarketObservation.effective_at >= datetime.combine(start, datetime.min.time()))
        if end:
            statement = statement.where(MarketObservation.effective_at < datetime.combine(end, datetime.max.time()))
        rows = list(db.execute(statement.order_by(MarketObservation.effective_at)))
        if rows:
            return [
                _from_observation_parts(observation, artifact, source, instrument.symbol)
                for observation, artifact, source in rows
            ]
    if not allow_legacy_fallback:
        return []
    # Provider ingestion normalizes symbols to uppercase. Keeping this predicate
    # sargable lets PostgreSQL use the existing (symbol, trade_date, source)
    # unique index instead of scanning the entire price table for every holding.
    statement = select(MarketPrice).where(MarketPrice.symbol == normalized_symbol)
    if not synthetic_market_data_allowed():
        statement = statement.where(func.lower(MarketPrice.source) != "mock")
    if start:
        statement = statement.where(MarketPrice.trade_date >= start)
    if end:
        statement = statement.where(MarketPrice.trade_date <= end)
    legacy = list(db.scalars(statement.order_by(MarketPrice.trade_date)))
    return [
        CanonicalPrice(
            instrument_id=instrument.id if instrument else None,
            symbol=row.symbol,
            trade_date=row.trade_date,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            previous_close=row.previous_close,
            volume=row.volume,
            market_cap=row.market_cap,
            source=row.source,
            source_url=row.source_url,
            artifact_id=None,
            artifact_sha256=None,
            observed_at=row.ingested_at,
            adjustment_state="unknown",
            quality_status="legacy_fallback",
        )
        for row in legacy
    ]


def canonical_prices_for_date(db: Session, trade_date: date) -> list[CanonicalPrice]:
    start = datetime.combine(trade_date, datetime.min.time())
    end = start + timedelta(days=1)
    statement = (
        select(MarketObservation)
        .join(SourceArtifact, SourceArtifact.id == MarketObservation.artifact_id)
        .join(DataSource, DataSource.id == SourceArtifact.data_source_id)
        .where(
            MarketObservation.is_selected.is_(True),
            MarketObservation.frequency == "daily",
            MarketObservation.effective_at >= start,
            MarketObservation.effective_at < end,
            MarketObservation.instrument_id.is_not(None),
        )
        .order_by(MarketObservation.instrument_id)
    )
    if not synthetic_market_data_allowed():
        statement = statement.where(
            ~func.lower(DataSource.name).in_(SYNTHETIC_SOURCE_NAMES),
            ~func.lower(SourceArtifact.source_url).like("demo://%"),
            ~func.lower(SourceArtifact.source_url).like("normalized://mock/%"),
        )
    rows = list(db.scalars(statement))
    output = []
    for row in rows:
        instrument = db.get(Instrument, row.instrument_id)
        if instrument:
            output.append(_from_observation(db, row, instrument.symbol))
    return output


def latest_price(db: Session, symbol: str, as_of: date | None = None) -> CanonicalPrice | None:
    """Return one canonical row without materializing the symbol's full history."""

    normalized_symbol = symbol.strip().upper()
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == normalized_symbol))
    if instrument:
        statement = (
            select(MarketObservation, SourceArtifact, DataSource)
            .join(SourceArtifact, SourceArtifact.id == MarketObservation.artifact_id)
            .join(DataSource, DataSource.id == SourceArtifact.data_source_id)
            .where(
                MarketObservation.instrument_id == instrument.id,
                MarketObservation.is_selected.is_(True),
                MarketObservation.frequency == "daily",
            )
        )
        if not synthetic_market_data_allowed():
            statement = statement.where(
                ~func.lower(DataSource.name).in_(SYNTHETIC_SOURCE_NAMES),
                ~func.lower(SourceArtifact.source_url).like("demo://%"),
                ~func.lower(SourceArtifact.source_url).like("normalized://mock/%"),
            )
        if as_of:
            statement = statement.where(
                MarketObservation.effective_at < datetime.combine(as_of, datetime.max.time())
            )
        row = db.execute(statement.order_by(MarketObservation.effective_at.desc()).limit(1)).first()
        if row:
            observation, artifact, source = row
            return _from_observation_parts(observation, artifact, source, instrument.symbol)

    statement = select(MarketPrice).where(MarketPrice.symbol == normalized_symbol)
    if not synthetic_market_data_allowed():
        statement = statement.where(func.lower(MarketPrice.source) != "mock")
    if as_of:
        statement = statement.where(MarketPrice.trade_date <= as_of)
    row = db.scalar(statement.order_by(MarketPrice.trade_date.desc()).limit(1))
    if row is None:
        return None
    return CanonicalPrice(
        instrument_id=instrument.id if instrument else None,
        symbol=row.symbol,
        trade_date=row.trade_date,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        previous_close=row.previous_close,
        volume=row.volume,
        market_cap=row.market_cap,
        source=row.source,
        source_url=row.source_url,
        artifact_id=None,
        artifact_sha256=None,
        observed_at=row.ingested_at,
        adjustment_state="unknown",
        quality_status="legacy_fallback",
    )
