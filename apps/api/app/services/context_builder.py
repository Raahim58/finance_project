"""Deterministic, read-only Canonical Intelligence Context assembler.

The builder deliberately has no ingestion, persistence, notification, or LLM dependency.
Callers may pass its structured deficiencies to ``ContextDeficiencyBridge``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, Callable

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.models.market import MarketPrice, SectorDailyStats
from app.models.portfolio import Portfolio, PortfolioHolding, PortfolioTransaction
from app.models.user import User
from app.models.workstation import (
    CompanyScreeningSnapshot,
    DataSource,
    FinancialFact,
    Instrument,
    MacroObservation,
    MarketObservation,
    NormalizedEvent,
    NormalizedEventSubject,
    PortfolioIPSVersion,
    SourceArtifact,
    StandardizedFinancialFact,
)
from app.schemas.intelligence_context import (
    CONTEXT_CONTRACT_VERSION,
    ContextDeficiency,
    ContextReceipt,
    ContextScope,
    ContextSection,
    ContextSectionName,
    ContextState,
    EvidenceReference,
    IntelligenceContext,
    IntelligenceContextRequest,
    ResearchPurpose,
)
from app.schemas.rag import RagSearchRequest
from app.services.canonical_market_service import latest_price
from app.services.event_intelligence_service import list_normalized_events
from app.services.market_service import get_sectors
from app.services.portfolio_service import get_portfolio_summary
from app.services.rag_service import search_rag
from app.services.regime_service import macro_regime
from app.services.trading_calendar_service import sessions_between


PURPOSE_QUERIES = {
    ResearchPurpose.RECENT_CHANGES: "recent company changes announcements results and material developments",
    ResearchPurpose.OUTLOOK: "company outlook guidance demand capacity strategy and expectations",
    ResearchPurpose.RISKS: "company risks headwinds litigation regulation leverage and downside",
    ResearchPurpose.DRIVERS: "company earnings revenue margin valuation and operating drivers",
}


def _canonical(value: Any) -> str:
    return json.dumps(jsonable_encoder(value), sort_keys=True, separators=(",", ":"), default=str)


def _hash(*parts: Any) -> str:
    return hashlib.sha256("|".join(_canonical(part) for part in parts).encode()).hexdigest()


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _evidence(
    classification: str,
    underlying_id: str,
    source: str,
    *,
    as_of: Any = None,
    source_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"ev_{_hash(classification, underlying_id)[:24]}",
        classification=classification,
        source=source,
        source_url=source_url,
        as_of=as_of,
        underlying_id=underlying_id,
        metadata=metadata or {},
    )


def _deficiency(
    instrument: Instrument,
    category: str,
    state: ContextState,
    reason: str,
    expected: dict[str, Any],
    *,
    urgency: str = "normal",
) -> ContextDeficiency:
    fingerprint = _hash("instrument", instrument.id, category, expected)
    return ContextDeficiency(
        deficiency_id=f"def_{fingerprint[:24]}",
        entity_type="instrument",
        entity_key=instrument.symbol,
        category=category,
        observed_state=state,
        expected=expected,
        reason=reason,
        urgency=urgency,
        fingerprint=fingerprint,
    )


def _section(
    name: ContextSectionName,
    state: ContextState,
    data: Any,
    evidence: list[EvidenceReference],
    *,
    as_of: Any = None,
    provenance: dict[str, Any] | None = None,
    errors: list[str] | None = None,
) -> ContextSection:
    dependency_hash = _hash(name.value, state.value, data, [item.evidence_id for item in evidence])
    return ContextSection(
        name=name,
        state=state,
        as_of=as_of,
        data=data,
        evidence=evidence,
        provenance=provenance or {},
        errors=errors or [],
        dependency_hash=dependency_hash,
    )


@dataclass
class _CachedSection:
    section: ContextSection
    deficiencies: list[ContextDeficiency]
    expires_at: datetime


class ContextSectionCache:
    """Short-lived process cache; authoritative data is always checked before reuse."""

    def __init__(self, ttl: timedelta = timedelta(minutes=5)) -> None:
        self.ttl = ttl
        self._items: dict[tuple[str, ...], _CachedSection] = {}

    def get(
        self, key: tuple[str, ...], dependency_hash: str, now: datetime
    ) -> tuple[ContextSection, list[ContextDeficiency]] | None:
        cached = self._items.get(key)
        if cached and cached.expires_at > now and cached.section.dependency_hash == dependency_hash:
            reused = cached.section.model_copy(deep=True)
            reused.reused = True
            return reused, [item.model_copy(deep=True) for item in cached.deficiencies]
        return None

    def put(
        self,
        key: tuple[str, ...],
        section: ContextSection,
        deficiencies: list[ContextDeficiency],
        now: datetime,
    ) -> None:
        self._items[key] = _CachedSection(
            section.model_copy(deep=True),
            [item.model_copy(deep=True) for item in deficiencies],
            now + self.ttl,
        )


class ContextBuilder:
    """Highest-level deterministic seam for the Phase 7A contract."""

    def __init__(
        self, *, cache: ContextSectionCache | None = None, now: Callable[[], datetime] | None = None
    ) -> None:
        self.cache = cache or ContextSectionCache()
        self.now = now or (lambda: datetime.now(UTC))

    def build(
        self, db: Session, user: User, request: IntelligenceContextRequest
    ) -> IntelligenceContext:
        build_started = perf_counter()
        built_at = self.now()
        instrument = db.scalar(
            select(Instrument).where(func.upper(Instrument.symbol) == request.symbol.upper())
        )
        if instrument is None:
            raise HTTPException(status_code=404, detail="Instrument not found")
        portfolio, ips = self._validate_personalized_scope(db, user, request)
        context_id = (
            f"ctx_{_hash(CONTEXT_CONTRACT_VERSION, user.id, request.model_dump(mode='json'))[:24]}"
        )

        sections: dict[str, ContextSection] = {}
        deficiencies: list[ContextDeficiency] = []
        section_durations: dict[str, float] = {}
        for name in request.resolved_sections():
            section_started = perf_counter()
            portfolio_cache_key = (
                request.portfolio_id or "-"
                if name in {ContextSectionName.PORTFOLIO, ContextSectionName.IPS}
                else "-"
            )
            cache_key = (
                CONTEXT_CONTRACT_VERSION,
                user.id,
                instrument.id,
                portfolio_cache_key,
                name.value,
                request.question or request.research_purpose.value
                if request.research_purpose
                else request.question or "-",
            )
            dependency_hash = self._dependency_hash(
                db, user, request, instrument, portfolio, ips, name, built_at
            )
            cached = self.cache.get(cache_key, dependency_hash, built_at)
            if cached is not None:
                value, missing = cached
                sections[name.value] = value
                deficiencies.extend(missing)
                section_durations[name.value] = round((perf_counter() - section_started) * 1000, 3)
                continue
            try:
                value, missing = self._build_section(
                    db, user, request, instrument, portfolio, ips, name
                )
            except Exception as exc:  # section failure is intentionally isolated
                value = _section(
                    name,
                    ContextState.NOT_EVALUATED,
                    None,
                    [],
                    errors=[f"{type(exc).__name__}: {str(exc)[:240]}"],
                    provenance={"failure_isolated": True},
                )
                missing = [
                    _deficiency(
                        instrument,
                        name.value,
                        ContextState.NOT_EVALUATED,
                        "The authoritative section provider could not complete.",
                        {"provider": name.value, "retry": "coordinator_policy"},
                    )
                ]
            value.dependency_hash = dependency_hash
            sections[name.value] = value
            if not value.errors:
                self.cache.put(cache_key, value, missing, built_at)
            section_durations[name.value] = round((perf_counter() - section_started) * 1000, 3)
            deficiencies.extend(missing)

        evidence_ids = sorted(
            {item.evidence_id for section in sections.values() for item in section.evidence}
        )
        states = {name: section.state for name, section in sections.items()}
        dependencies = {name: section.dependency_hash for name, section in sections.items()}
        content_hash = _hash(
            CONTEXT_CONTRACT_VERSION,
            request.scope.value,
            instrument.symbol,
            request.portfolio_id,
            {
                name: section.model_dump(exclude={"reused"}, mode="json")
                for name, section in sections.items()
            },
            [item.fingerprint for item in deficiencies],
        )
        receipt = ContextReceipt(
            context_id=context_id,
            built_at=built_at,
            content_hash=content_hash,
            evidence_ids=evidence_ids,
            calculation_runs=sorted(
                item.underlying_id
                for section in sections.values()
                for item in section.evidence
                if item.classification == "calculation"
            ),
            section_states=states,
            dependency_hashes=dependencies,
            build_duration_ms=round((perf_counter() - build_started) * 1000, 3),
            section_duration_ms=section_durations,
        )
        degraded = any(
            state not in {ContextState.CURRENT, ContextState.NOT_REQUESTED}
            for state in states.values()
        )
        return IntelligenceContext(
            context_id=context_id,
            scope=request.scope,
            symbol=instrument.symbol,
            portfolio_id=request.portfolio_id,
            built_at=built_at,
            status="degraded" if degraded else "ready",
            message="Some requested data is unavailable or not current; refresh may be requested."
            if degraded
            else None,
            sections=sections,
            deficiencies=deficiencies,
            receipt=receipt,
        )

    def _dependency_hash(
        self,
        db: Session,
        user: User,
        request: IntelligenceContextRequest,
        instrument: Instrument,
        portfolio: Portfolio | None,
        ips: PortfolioIPSVersion | None,
        name: ContextSectionName,
        now: datetime,
    ) -> str:
        """Read cheap authoritative version keys before invoking a section provider."""

        base = [CONTEXT_CONTRACT_VERSION, name.value, instrument.id]
        if name == ContextSectionName.COMPANY_FACTS:
            filing = [
                tuple(row)
                for row in db.execute(
                    select(
                        FinancialFact.id,
                        FinancialFact.version,
                        FinancialFact.value,
                        FinancialFact.filing_date,
                        FinancialFact.period_end,
                    ).where(FinancialFact.instrument_id == instrument.id)
                )
            ]
            standardized = [
                tuple(row)
                for row in db.execute(
                    select(
                        StandardizedFinancialFact.id,
                        StandardizedFinancialFact.value,
                        StandardizedFinancialFact.retrieved_at,
                        StandardizedFinancialFact.quality_status,
                    ).where(StandardizedFinancialFact.instrument_id == instrument.id)
                )
            ]
            return _hash(base, instrument.name, instrument.sector, filing, standardized)
        if name == ContextSectionName.MARKET_RISK:
            price = latest_price(db, instrument.symbol)
            snapshot = db.scalar(
                select(CompanyScreeningSnapshot)
                .where(CompanyScreeningSnapshot.instrument_id == instrument.id)
                .order_by(CompanyScreeningSnapshot.as_of_date.desc())
                .limit(1)
            )
            cadence_minutes = 5
            if price and price.artifact_id:
                artifact = db.get(SourceArtifact, price.artifact_id)
                source = db.get(DataSource, artifact.data_source_id) if artifact else None
                cadence_minutes = (
                    source.freshness_sla_minutes or cadence_minutes if source else cadence_minutes
                )
            cadence_bucket = int(now.timestamp() // max(60, cadence_minutes * 60))
            price_key = (
                None
                if price is None
                else (
                    price.artifact_id,
                    price.trade_date,
                    price.close,
                    price.previous_close,
                    price.volume,
                    price.observed_at,
                )
            )
            snapshot_key = (
                None
                if snapshot is None
                else (snapshot.id, snapshot.computed_at, snapshot.metrics_json)
            )
            return _hash(base, price_key, snapshot_key, cadence_bucket)
        if name == ContextSectionName.SECTOR:
            observations = [
                tuple(row)
                for row in db.execute(
                    select(
                        MarketObservation.id,
                        MarketObservation.artifact_id,
                        MarketObservation.effective_at,
                    )
                    .join(Instrument, Instrument.id == MarketObservation.instrument_id)
                    .where(
                        Instrument.sector == instrument.sector,
                        MarketObservation.is_selected.is_(True),
                    )
                    .order_by(MarketObservation.effective_at.desc())
                    .limit(200)
                )
            ]
            fallback = [
                tuple(row)
                for row in db.execute(
                    select(
                        SectorDailyStats.id,
                        SectorDailyStats.trade_date,
                        SectorDailyStats.total_value,
                        SectorDailyStats.average_change_percent,
                    )
                    .where(SectorDailyStats.sector == instrument.sector)
                    .order_by(SectorDailyStats.trade_date.desc())
                    .limit(2)
                )
            ]
            legacy = tuple(
                db.execute(
                    select(func.max(MarketPrice.trade_date), func.count(MarketPrice.id))
                ).one()
            )
            return _hash(base, instrument.sector, observations, fallback, legacy)
        if name == ContextSectionName.MACRO:
            observations = [
                tuple(row)
                for row in db.execute(
                    select(
                        MacroObservation.id,
                        MacroObservation.revision,
                        MacroObservation.value,
                        MacroObservation.release_at,
                        MacroObservation.retrieved_at,
                        MacroObservation.is_selected,
                    ).where(MacroObservation.is_selected.is_(True))
                )
            ]
            breadth = tuple(
                db.execute(
                    select(func.max(SectorDailyStats.trade_date), func.count(SectorDailyStats.id))
                ).one()
            )
            return _hash(base, observations, breadth)
        if name == ContextSectionName.EVENTS:
            rows = [
                tuple(row)
                for row in db.execute(
                    select(
                        NormalizedEvent.id,
                        NormalizedEvent.updated_at,
                        NormalizedEvent.materiality,
                        NormalizedEvent.freshness_status,
                    )
                    .join(
                        NormalizedEventSubject,
                        NormalizedEventSubject.normalized_event_id == NormalizedEvent.id,
                    )
                    .where(
                        NormalizedEventSubject.subject_type == "instrument",
                        func.upper(NormalizedEventSubject.subject_key) == instrument.symbol.upper(),
                    )
                )
            ]
            return _hash(base, request.event_limit, rows)
        if name == ContextSectionName.RAG_EVIDENCE:
            query = request.question or (
                PURPOSE_QUERIES.get(request.research_purpose) if request.research_purpose else None
            )
            documents = [
                tuple(row)
                for row in db.execute(
                    select(
                        Document.id, Document.content_hash, Document.status, Document.parsed_at
                    ).where(
                        Document.symbol == instrument.symbol,
                        (Document.visibility == "public") | (Document.owner_user_id == user.id),
                    )
                )
            ]
            chunk_count = (
                db.scalar(
                    select(func.count(DocumentChunk.id))
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .where(
                        Document.symbol == instrument.symbol,
                        (Document.visibility == "public") | (Document.owner_user_id == user.id),
                    )
                )
                or 0
            )
            return _hash(base, query, request.rag_limit, documents, chunk_count)
        if name == ContextSectionName.IPS:
            return _hash(
                base,
                None
                if ips is None
                else (ips.id, ips.version, ips.status, ips.constraints_json, ips.confirmed_at),
            )
        assert name == ContextSectionName.PORTFOLIO and portfolio is not None
        holdings = [
            tuple(row)
            for row in db.execute(
                select(
                    PortfolioHolding.id,
                    PortfolioHolding.symbol,
                    PortfolioHolding.quantity,
                    PortfolioHolding.updated_at,
                ).where(PortfolioHolding.portfolio_id == portfolio.id)
            )
        ]
        transactions = tuple(
            db.execute(
                select(
                    func.count(PortfolioTransaction.id), func.max(PortfolioTransaction.created_at)
                ).where(PortfolioTransaction.portfolio_id == portfolio.id)
            ).one()
        )
        symbols = [row[1] for row in holdings]
        prices = (
            [
                tuple(row)
                for row in db.execute(
                    select(
                        MarketObservation.instrument_id,
                        func.max(MarketObservation.effective_at),
                        func.max(MarketObservation.artifact_id),
                    )
                    .join(Instrument, Instrument.id == MarketObservation.instrument_id)
                    .where(
                        Instrument.symbol.in_(symbols),
                        MarketObservation.is_selected.is_(True),
                    )
                    .group_by(MarketObservation.instrument_id)
                )
            ]
            if symbols
            else []
        )
        return _hash(base, portfolio.id, portfolio.updated_at, holdings, transactions, prices)

    @staticmethod
    def _validate_personalized_scope(
        db: Session, user: User, request: IntelligenceContextRequest
    ) -> tuple[Portfolio | None, PortfolioIPSVersion | None]:
        if request.scope == ContextScope.COMPANY_INTELLIGENCE:
            return None, None
        portfolio = db.get(Portfolio, request.portfolio_id)
        if portfolio is None or portfolio.user_id != user.id:
            raise HTTPException(status_code=404, detail="Portfolio not found")
        ips = (
            db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id)
            if portfolio.selected_ips_version_id
            else None
        )
        if request.scope == ContextScope.SECURITY_FIT and (
            ips is None or ips.status != "confirmed"
        ):
            raise HTTPException(
                status_code=422,
                detail="Security Fit requires the selected portfolio's confirmed IPS",
            )
        return portfolio, ips

    def _build_section(
        self,
        db: Session,
        user: User,
        request: IntelligenceContextRequest,
        instrument: Instrument,
        portfolio: Portfolio | None,
        ips: PortfolioIPSVersion | None,
        name: ContextSectionName,
    ) -> tuple[ContextSection, list[ContextDeficiency]]:
        providers = {
            ContextSectionName.COMPANY_FACTS: self._company_facts,
            ContextSectionName.MARKET_RISK: self._market_risk,
            ContextSectionName.SECTOR: self._sector,
            ContextSectionName.MACRO: self._macro,
            ContextSectionName.EVENTS: self._events,
            ContextSectionName.RAG_EVIDENCE: self._rag,
        }
        if name == ContextSectionName.PORTFOLIO:
            return self._portfolio(db, user, instrument, portfolio)
        if name == ContextSectionName.IPS:
            return self._ips(instrument, ips)
        return providers[name](db, user, request, instrument)

    @staticmethod
    def _portfolio(db: Session, user: User, instrument: Instrument, portfolio: Portfolio | None):
        assert portfolio is not None
        summary = get_portfolio_summary(db, user, portfolio.id)
        holding = next((row for row in summary.holdings if row.symbol == instrument.symbol), None)
        total = float(summary.total_value)
        data = {
            "id": portfolio.id,
            "name": portfolio.name,
            "base_currency": portfolio.base_currency,
            "source": summary.data_source,
            "valuation_complete": summary.valuation_complete,
            "unpriced_symbols": summary.unpriced_symbols,
            "total_value": total,
            "security_exposure": {
                "quantity": float(holding.quantity) if holding else 0.0,
                "market_value": float(holding.market_value) if holding else 0.0,
                "weight": float(holding.market_value) / total if holding and total else 0.0,
            },
        }
        evidence = [
            _evidence(
                "calculation",
                f"portfolio:{portfolio.id}:{portfolio.updated_at.isoformat()}",
                "portfolio_valuation",
                as_of=summary.data_freshness_date,
            )
        ]
        state = ContextState.CURRENT if summary.valuation_complete else ContextState.INCOMPLETE
        missing = (
            []
            if summary.valuation_complete
            else [
                _deficiency(
                    instrument,
                    "portfolio_valuation",
                    ContextState.INCOMPLETE,
                    "One or more holdings lack a canonical price.",
                    {"portfolio_id": portfolio.id, "unpriced_symbols": summary.unpriced_symbols},
                    urgency="high",
                )
            ]
        )
        return _section(
            ContextSectionName.PORTFOLIO, state, data, evidence, as_of=summary.data_freshness_date
        ), missing

    @staticmethod
    def _ips(instrument: Instrument, ips: PortfolioIPSVersion | None):
        if ips is None or ips.status != "confirmed":
            return _section(ContextSectionName.IPS, ContextState.MISSING, None, []), [
                _deficiency(
                    instrument,
                    "confirmed_ips",
                    ContextState.MISSING,
                    "The selected portfolio has no confirmed IPS.",
                    {"status": "confirmed", "scope": "selected_portfolio"},
                    urgency="high",
                )
            ]
        constraints = json.loads(ips.constraints_json or "{}")
        data = {
            "id": ips.id,
            "portfolio_id": ips.portfolio_id,
            "version": ips.version,
            "status": ips.status,
            "confirmed_at": ips.confirmed_at,
            "required_return": ips.required_return,
            "terms": constraints,
        }
        evidence = [
            _evidence(
                "mandate",
                f"ips:{ips.id}:v{ips.version}",
                "confirmed_portfolio_ips",
                as_of=ips.confirmed_at,
            )
        ]
        return _section(
            ContextSectionName.IPS, ContextState.CURRENT, data, evidence, as_of=ips.confirmed_at
        ), []

    @staticmethod
    def _company_facts(
        db: Session, _user: User, _request: IntelligenceContextRequest, instrument: Instrument
    ):
        filing = list(
            db.scalars(
                select(FinancialFact)
                .where(FinancialFact.instrument_id == instrument.id)
                .order_by(FinancialFact.period_end.desc(), FinancialFact.version.desc())
                .limit(100)
            )
        )
        standardized = list(
            db.scalars(
                select(StandardizedFinancialFact)
                .where(
                    StandardizedFinancialFact.instrument_id == instrument.id,
                    StandardizedFinancialFact.quality_status == "observed",
                )
                .order_by(StandardizedFinancialFact.period_end.desc())
                .limit(100)
            )
        )
        facts = [
            {
                "id": row.id,
                "metric": row.taxonomy_key,
                "period_type": row.period_type,
                "period_end": row.period_end,
                "filing_date": row.filing_date,
                "value": row.value,
                "unit": row.unit,
                "currency": row.currency,
                "document_id": row.document_id,
                "version": row.version,
            }
            for row in filing
        ] + [
            {
                "id": row.id,
                "metric": row.metric,
                "period_type": row.period_type,
                "period_end": row.period_end,
                "value": row.value,
                "unit": row.unit,
                "currency": row.currency,
                "source_url": row.source_url,
                "classification": row.classification,
            }
            for row in standardized
        ]
        evidence = [
            _evidence(
                "structured_fact",
                f"financial_fact:{row.id}:v{row.version}",
                row.source_label or "financial_facts",
                as_of=row.filing_date or row.period_end,
                metadata={"document_id": row.document_id, "page_number": row.page_number},
            )
            for row in filing
        ] + [
            _evidence(
                "structured_fact",
                f"standardized_fact:{row.id}:{_hash(row.value, row.retrieved_at)[:16]}",
                row.source,
                as_of=row.retrieved_at,
                source_url=row.source_url,
            )
            for row in standardized
        ]
        data = {
            "instrument": {
                "id": instrument.id,
                "symbol": instrument.symbol,
                "name": instrument.name,
                "sector": instrument.sector,
                "currency": instrument.currency,
                "type": instrument.instrument_type,
            },
            "fundamentals": facts,
        }
        if facts:
            as_of = max(
                (row.get("filing_date") or row["period_end"] for row in facts), default=None
            )
            return _section(
                ContextSectionName.COMPANY_FACTS,
                ContextState.CURRENT,
                data,
                evidence,
                as_of=as_of,
                provenance={"exact_values": "structured_database_only"},
            ), []
        missing = [
            _deficiency(
                instrument,
                "financial_facts",
                ContextState.MISSING,
                "No observed structured financial facts are available.",
                {"dataset": "financial_facts", "cadence": "reporting_period"},
            )
        ]
        return _section(
            ContextSectionName.COMPANY_FACTS,
            ContextState.INCOMPLETE,
            data,
            evidence,
            provenance={"exact_values": "structured_database_only"},
        ), missing

    def _market_risk(
        self, db: Session, _user: User, _request: IntelligenceContextRequest, instrument: Instrument
    ):
        price = latest_price(db, instrument.symbol)
        snapshot = db.scalar(
            select(CompanyScreeningSnapshot)
            .where(CompanyScreeningSnapshot.instrument_id == instrument.id)
            .order_by(CompanyScreeningSnapshot.as_of_date.desc())
            .limit(1)
        )
        if price is None:
            return _section(ContextSectionName.MARKET_RISK, ContextState.MISSING, None, []), [
                _deficiency(
                    instrument,
                    "market_price",
                    ContextState.MISSING,
                    "No selected canonical market observation is available.",
                    {"dataset": "daily_market", "cadence": "trading_session"},
                    urgency="high",
                )
            ]
        artifact = db.get(SourceArtifact, price.artifact_id) if price.artifact_id else None
        source = db.get(DataSource, artifact.data_source_id) if artifact else None
        state = ContextState.CURRENT
        now = self.now()
        intervening_sessions = (
            sessions_between(db, price.trade_date + timedelta(days=1), now.date())
            if price.trade_date < now.date()
            else []
        )
        expected = {
            "cadence": "trading_session",
            "source_sla_minutes": source.freshness_sla_minutes if source else None,
            "intervening_sessions": [row.session_date for row in intervening_sessions],
            "calendar_statuses": sorted({row.status for row in intervening_sessions}),
        }
        outside_source_sla = bool(
            source
            and source.freshness_sla_minutes
            and artifact
            and _utc(artifact.retrieved_at) < now - timedelta(minutes=source.freshness_sla_minutes)
        )
        if intervening_sessions or (price.trade_date == now.date() and outside_source_sla):
            state = ContextState.STALE
        data = {
            "price": {
                "trade_date": price.trade_date,
                "close": price.close,
                "previous_close": price.previous_close,
                "change_percent": price.change_percent,
                "volume": price.volume,
                "market_cap": price.market_cap,
                "adjustment_state": price.adjustment_state,
                "quality_status": price.quality_status,
            },
            "risk_metrics": json.loads(snapshot.metrics_json) if snapshot else None,
            "risk_calculation_as_of": snapshot.as_of_date if snapshot else None,
        }
        market_version = (
            price.artifact_id
            or _hash(
                price.trade_date, price.close, price.previous_close, price.volume, price.observed_at
            )[:16]
        )
        evidence = [
            _evidence(
                "market_observation",
                f"market:{market_version}:symbol:{instrument.symbol}:date:{price.trade_date}",
                price.source,
                as_of=price.observed_at or price.trade_date,
                source_url=price.source_url,
            )
        ]
        if snapshot:
            evidence.append(
                _evidence(
                    "calculation",
                    f"screening:{snapshot.id}:{snapshot.computed_at.isoformat()}",
                    "company_screening",
                    as_of=snapshot.as_of_date,
                )
            )
        missing = (
            []
            if state == ContextState.CURRENT
            else [
                _deficiency(
                    instrument,
                    "market_price",
                    state,
                    "The authoritative market source is outside its own freshness SLA.",
                    expected,
                    urgency="high",
                )
            ]
        )
        if snapshot is None:
            missing.append(
                _deficiency(
                    instrument,
                    "company_risk_metrics",
                    ContextState.NOT_EVALUATED,
                    "No deterministic company risk calculation is available.",
                    {"dataset": "company_screening", "dependency": "market_history"},
                )
            )
            if state == ContextState.CURRENT:
                state = ContextState.INCOMPLETE
        return _section(
            ContextSectionName.MARKET_RISK,
            state,
            data,
            evidence,
            as_of=price.trade_date,
            provenance={"freshness_policy": expected},
        ), missing

    @staticmethod
    def _sector(
        db: Session, _user: User, _request: IntelligenceContextRequest, instrument: Instrument
    ):
        rows = get_sectors(db)
        selected = next(
            (row for row in rows if row.sector.lower() == (instrument.sector or "").lower()), None
        )
        if selected is None:
            return _section(ContextSectionName.SECTOR, ContextState.MISSING, None, []), [
                _deficiency(
                    instrument,
                    "sector_context",
                    ContextState.MISSING,
                    "No canonical sector comparison is available.",
                    {"sector": instrument.sector, "cadence": "trading_session"},
                )
            ]
        data = {
            "company_sector": selected.model_dump(),
            "comparisons": [row.model_dump() for row in rows[:20]],
        }
        evidence = [
            _evidence(
                "structured_fact",
                f"sector:{selected.sector}:{selected.trade_date}:{selected.source}:{_hash(selected.model_dump())[:16]}",
                selected.source,
                as_of=selected.trade_date,
            )
        ]
        return _section(
            ContextSectionName.SECTOR,
            ContextState.CURRENT,
            data,
            evidence,
            as_of=selected.trade_date,
        ), []

    @staticmethod
    def _macro(
        db: Session, user: User, _request: IntelligenceContextRequest, instrument: Instrument
    ):
        data = macro_regime(db, user, None)
        evidence = []
        for dimension, observation in data.get("dimensions", {}).items():
            underlying = (
                observation.get("artifact_id")
                or f"{observation.get('series_key')}:{observation.get('effective_date') or observation.get('trade_date')}"
            )
            source_value = (
                observation.get("series_name") or observation.get("source") or "macro_observations"
            )
            source_name = (
                ", ".join(str(item) for item in source_value)
                if isinstance(source_value, list)
                else str(source_value)
            )
            evidence.append(
                _evidence(
                    "structured_fact",
                    f"macro:{underlying}",
                    source_name,
                    as_of=observation.get("release_at")
                    or observation.get("effective_date")
                    or observation.get("trade_date"),
                    metadata={"dimension": dimension},
                )
            )
        state = (
            ContextState.NOT_EVALUATED
            if data.get("regime") == "not_evaluated"
            else ContextState.CURRENT
        )
        missing = (
            []
            if state == ContextState.CURRENT
            else [
                _deficiency(
                    instrument,
                    "macro_regime",
                    state,
                    "Not enough selected structured observations exist to classify the regime.",
                    {"minimum_evaluable_dimensions": 2, "cadence": "source_release"},
                )
            ]
        )
        return _section(
            ContextSectionName.MACRO,
            state,
            data,
            evidence,
            provenance={"classification": "rule_based_v1", "observations_separate": True},
        ), missing

    @staticmethod
    def _events(
        db: Session, _user: User, request: IntelligenceContextRequest, instrument: Instrument
    ):
        events = list_normalized_events(
            db,
            subject_type="instrument",
            subject_key=instrument.symbol,
            view="company_relevant",
            limit=request.event_limit,
        )
        admitted = [row for row in events if row.get("materiality") in {"medium", "high"}][
            : request.event_limit
        ]
        evidence = [
            _evidence(
                "event",
                f"normalized_event:{row['id']}:{row.get('detection_version')}:{_hash(row)[:16]}",
                "normalized_event_intelligence",
                as_of=row.get("occurred_at"),
                metadata={
                    "materiality": row.get("materiality"),
                    "source_count": len(row.get("evidence", [])),
                },
            )
            for row in admitted
        ]
        state = ContextState.CURRENT if admitted else ContextState.MISSING
        missing = (
            []
            if admitted
            else [
                _deficiency(
                    instrument,
                    "relevant_events",
                    state,
                    "No material normalized company events are available.",
                    {
                        "materiality": ["medium", "high"],
                        "limit": request.event_limit,
                        "cadence": "event_driven",
                    },
                )
            ]
        )
        if admitted and all(row.get("freshness_status") == "stale" for row in admitted):
            state = ContextState.STALE
            missing = [
                _deficiency(
                    instrument,
                    "relevant_events",
                    state,
                    "All admitted events are stale under event intelligence's own policy.",
                    {"cadence": "event_driven", "limit": request.event_limit},
                )
            ]
        return _section(
            ContextSectionName.EVENTS,
            state,
            admitted,
            evidence,
            as_of=admitted[0]["occurred_at"] if admitted else None,
            provenance={"bounded_limit": request.event_limit},
        ), missing

    @staticmethod
    def _rag(db: Session, user: User, request: IntelligenceContextRequest, instrument: Instrument):
        query = request.question or (
            PURPOSE_QUERIES.get(request.research_purpose) if request.research_purpose else None
        )
        if not query:
            return _section(
                ContextSectionName.RAG_EVIDENCE,
                ContextState.NOT_REQUESTED,
                [],
                [],
                provenance={"reason": "no_question_or_research_purpose"},
            ), []
        response = search_rag(
            db,
            user,
            RagSearchRequest(query=query, symbols=[instrument.symbol], limit=request.rag_limit),
        )
        chunks = [chunk.model_dump() for chunk in response.chunks[: request.rag_limit]]
        evidence = [
            _evidence(
                "document_passage",
                f"chunk:{chunk.id}:document:{chunk.document_id}",
                chunk.citation.source_name,
                as_of=chunk.citation.created_at,
                source_url=chunk.source_url,
                metadata={
                    "citation_id": chunk.citation.id,
                    "document_id": chunk.document_id,
                    "page_number": chunk.page_number,
                    "score": chunk.score,
                },
            )
            for chunk in response.chunks[: request.rag_limit]
        ]
        state = ContextState.CURRENT if chunks else ContextState.MISSING
        missing = (
            []
            if chunks
            else [
                _deficiency(
                    instrument,
                    "rag_evidence",
                    state,
                    "No admissible document passages matched the supplied purpose.",
                    {
                        "query_mode": "question" if request.question else "predefined_purpose",
                        "purpose": request.research_purpose,
                        "limit": request.rag_limit,
                        "cadence": "event_driven",
                    },
                )
            ]
        )
        return _section(
            ContextSectionName.RAG_EVIDENCE,
            state,
            chunks,
            evidence,
            provenance={
                "query": query,
                "bounded_limit": request.rag_limit,
                "exact_values_allowed": False,
            },
        ), missing


# Application-scoped reuse seam. Consumers should use this shared builder rather than
# constructing a request-local cache; authoritative dependency hashes still govern reuse.
canonical_context_builder = ContextBuilder()


def build_intelligence_context(
    db: Session, user: User, request: IntelligenceContextRequest
) -> IntelligenceContext:
    return canonical_context_builder.build(db, user, request)
