"""Durable bridge from read-only context deficiencies to ingestion coordination."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.intelligence_context import (
    ContextDeficiencyRecord,
    ContextRefreshRequest,
    IntelligenceContextReceiptRecord,
)
from app.models.user import User
from app.schemas.intelligence_context import (
    ContextDeficiency,
    ContextState,
    IngestionWorkReference,
    IntelligenceContext,
    IntelligenceContextRequest,
)


TERMINAL_STATES = {"succeeded", "partial", "failed", "timed_out", "not_applicable"}


@dataclass(frozen=True)
class IngestionRoute:
    family: str | None
    mode: str | None
    reason: str

    @property
    def actionable(self) -> bool:
        return self.family is not None


class ContextIngestionRouter:
    """Map data semantics to ingestion families; callers never see worker details."""

    ROUTES = {
        "market_price": ("current_market", "live"),
        "sector_context": ("current_market", "live"),
        "portfolio_valuation": ("current_market", "live"),
        "company_risk_metrics": ("market_history", "historical"),
        "financial_facts": ("company_reports", "incremental"),
        "company_facts": ("company_reports", "incremental"),
        "macro_regime": ("macro", "release_cadence"),
        "macro": ("macro", "release_cadence"),
        "relevant_events": ("evidence", "live"),
        "events": ("evidence", "live"),
        "rag_evidence": ("evidence", "live"),
        "market_risk": ("current_market", "live"),
        "sector": ("current_market", "live"),
    }

    def decide(self, deficiency: ContextDeficiency) -> IngestionRoute:
        route = self.ROUTES.get(deficiency.category)
        if route is None:
            return IngestionRoute(None, None, "The deficiency requires user or application action, not ingestion.")
        return IngestionRoute(route[0], route[1], "Selected from deficiency category and expected cadence.")


class RoutedIngestionCoordinator:
    """Adapter for existing ingestion family dispatchers and their durable status lookup."""

    def __init__(
        self,
        dispatchers: Mapping[str, Callable[[ContextDeficiency, IngestionRoute], IngestionWorkReference]],
        status_lookup: Callable[[str], IngestionWorkReference],
        *,
        router: ContextIngestionRouter | None = None,
    ) -> None:
        self.dispatchers = dispatchers
        self.status_lookup = status_lookup
        self.router = router or ContextIngestionRouter()

    def schedule(self, deficiency: ContextDeficiency) -> IngestionWorkReference:
        route = self.router.decide(deficiency)
        if not route.actionable:
            return IngestionWorkReference(
                work_id=f"not_applicable:{deficiency.fingerprint}",
                state="not_applicable",
                coordinator=type(self).__name__,
            )
        dispatcher = self.dispatchers.get(route.family or "")
        if dispatcher is None:
            raise RuntimeError(f"No ingestion dispatcher is configured for {route.family}")
        return dispatcher(deficiency, route)

    def status(self, work_id: str) -> IngestionWorkReference:
        if work_id.startswith("not_applicable:"):
            return IngestionWorkReference(
                work_id=work_id,
                state="not_applicable",
                coordinator=type(self).__name__,
            )
        return self.status_lookup(work_id)


class IngestionCoordinator(Protocol):
    """Coordinator owns provider, task, queue, retry, and cadence selection."""

    def schedule(self, deficiency: ContextDeficiency) -> IngestionWorkReference: ...

    def status(self, work_id: str) -> IngestionWorkReference: ...


def _json(value) -> str:
    return json.dumps(jsonable_encoder(value), sort_keys=True, separators=(",", ":"))


def _upsert_deficiency(
    db: Session, deficiency: ContextDeficiency, now: datetime
) -> ContextDeficiencyRecord:
    """Atomically count equivalent deficiencies under concurrent context requests."""

    values = {
        "fingerprint": deficiency.fingerprint,
        "entity_type": deficiency.entity_type,
        "entity_key": deficiency.entity_key,
        "category": deficiency.category,
        "payload_json": _json(deficiency),
        "status": "open",
        "occurrence_count": 1,
        "first_seen_at": now,
        "last_seen_at": now,
    }
    dialect = db.get_bind().dialect.name
    factory = postgresql_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
    if factory is not None:
        statement = factory(ContextDeficiencyRecord).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[ContextDeficiencyRecord.fingerprint],
            set_={
                "occurrence_count": ContextDeficiencyRecord.occurrence_count + 1,
                "last_seen_at": now,
                "payload_json": values["payload_json"],
                "status": "open",
                "resolved_at": None,
            },
        ).returning(ContextDeficiencyRecord.id)
        row_id = db.scalar(statement)
        return db.get(ContextDeficiencyRecord, row_id, populate_existing=True)

    row = db.scalar(select(ContextDeficiencyRecord).where(
        ContextDeficiencyRecord.fingerprint == deficiency.fingerprint
    ).with_for_update())
    if row is None:
        try:
            with db.begin_nested():
                row = ContextDeficiencyRecord(**values)
                db.add(row)
                db.flush()
                return row
        except IntegrityError:
            row = db.scalar(select(ContextDeficiencyRecord).where(
                ContextDeficiencyRecord.fingerprint == deficiency.fingerprint
            ).with_for_update())
            if row is None:
                raise
    row.occurrence_count += 1
    row.last_seen_at = now
    row.payload_json = values["payload_json"]
    row.status = "open"
    row.resolved_at = None
    return row


class ContextDeficiencyBridge:
    def __init__(self, coordinator: IngestionCoordinator) -> None:
        self.coordinator = coordinator

    @classmethod
    def production(cls, db: Session, user: User) -> "ContextDeficiencyBridge":
        from app.services.context_ingestion_coordinator import DatabaseIngestionCoordinator

        return cls(DatabaseIngestionCoordinator(db, user_id=user.id))

    def record_and_schedule(
        self,
        db: Session,
        user: User,
        request: IntelligenceContextRequest,
        context: IntelligenceContext,
        *,
        active: bool = True,
    ) -> tuple[IntelligenceContext, ContextRefreshRequest | None]:
        """Persist/deduplicate deficiencies and delegate routing to the coordinator."""

        self.persist_receipt(db, user, context)
        if not context.deficiencies:
            db.commit()
            return context, None

        now = datetime.now(UTC)
        records: list[ContextDeficiencyRecord] = []
        for deficiency in context.deficiencies:
            row = _upsert_deficiency(db, deficiency, now)
            records.append(row)

        existing_work = self._existing_work(db, {row.id for row in records})
        work: list[dict] = []
        for row, deficiency in zip(records, context.deficiencies, strict=True):
            linked = existing_work.get(row.id)
            if linked is None:
                try:
                    reference = self.coordinator.schedule(deficiency)
                except Exception as exc:
                    reference = IngestionWorkReference(
                        work_id=f"schedule_failed:{row.id}",
                        state="failed",
                        coordinator=type(self.coordinator).__name__,
                    )
                    work.append({"deficiency_id": row.id, **reference.model_dump(), "error": f"{type(exc).__name__}: {str(exc)[:240]}"})
                    row.status = "failed"
                    continue
                linked = {"deficiency_id": row.id, **reference.model_dump()}
                row.status = "refreshing"
            work.append(linked)

        if work and all(item["state"] == "not_applicable" for item in work):
            db.commit()
            return context, None

        refresh = ContextRefreshRequest(
            user_id=user.id,
            context_id=context.context_id,
            request_json=_json(request),
            deficiency_ids_json=_json([row.id for row in records]),
            work_json=_json(work),
            status="refreshing" if any(item["state"] not in TERMINAL_STATES for item in work) else "terminal",
            active=active,
        )
        db.add(refresh)
        db.commit()
        refreshing = context.model_copy(deep=True)
        refreshing.status = "refreshing"
        refreshing.message = "Up-to-date data is being fetched. This context will refresh once the linked ingestion work finishes."
        for section in refreshing.sections.values():
            if section.state in {ContextState.MISSING, ContextState.STALE, ContextState.INCOMPLETE, ContextState.NOT_EVALUATED}:
                section.state = ContextState.REFRESHING
        return refreshing, refresh

    @staticmethod
    def _existing_work(db: Session, deficiency_ids: set[str]) -> dict[str, dict]:
        result: dict[str, dict] = {}
        pending = db.scalars(select(ContextRefreshRequest).where(ContextRefreshRequest.status.in_(("pending", "refreshing")))).all()
        for refresh in pending:
            for item in json.loads(refresh.work_json or "[]"):
                if item.get("deficiency_id") in deficiency_ids and item.get("state") not in TERMINAL_STATES:
                    result[item["deficiency_id"]] = item
        return result

    def reconcile(
        self,
        db: Session,
        refresh_id: str,
        *,
        rebuild: Callable[[IntelligenceContextRequest], IntelligenceContext],
        notify: Callable[[str, IntelligenceContext], None] | None = None,
    ) -> IntelligenceContext | None:
        """Rebuild exactly once when every linked work item becomes terminal."""

        refresh = db.get(ContextRefreshRequest, refresh_id, with_for_update=True)
        if refresh is None:
            raise ValueError("Context refresh request not found")
        if refresh.rebuild_count:
            return None
        work = json.loads(refresh.work_json or "[]")
        refreshed_work = []
        for item in work:
            if item["state"] in TERMINAL_STATES or item["work_id"].startswith("schedule_failed:"):
                refreshed_work.append(item)
                continue
            current = self.coordinator.status(item["work_id"])
            refreshed_work.append({"deficiency_id": item["deficiency_id"], **current.model_dump()})
        refresh.work_json = _json(refreshed_work)
        if any(item["state"] not in TERMINAL_STATES for item in refreshed_work):
            refresh.status = "refreshing"
            db.commit()
            return None

        refresh.status = "terminal"
        refresh.terminal_at = datetime.now(UTC)
        if not refresh.active:
            refresh.needs_rebuild = True
            db.commit()
            return None

        request = IntelligenceContextRequest.model_validate(json.loads(refresh.request_json))
        rebuilt = rebuild(request)
        refresh.rebuild_count = 1
        refresh.needs_rebuild = False
        refresh.status = "rebuilt"
        self._resolve_absent_deficiencies(db, refresh, rebuilt)
        if notify:
            notify(refresh.user_id, rebuilt)
            refresh.notified_at = datetime.now(UTC)
        db.commit()
        return rebuilt

    def rebuild_if_needed(
        self,
        db: Session,
        refresh_id: str,
        *,
        rebuild: Callable[[IntelligenceContextRequest], IntelligenceContext],
    ) -> IntelligenceContext | None:
        """Lazy rebuild for a context that became inactive before ingestion completed."""

        refresh = db.get(ContextRefreshRequest, refresh_id, with_for_update=True)
        if refresh is None or not refresh.needs_rebuild or refresh.rebuild_count:
            return None
        request = IntelligenceContextRequest.model_validate(json.loads(refresh.request_json))
        rebuilt = rebuild(request)
        refresh.rebuild_count = 1
        refresh.needs_rebuild = False
        refresh.status = "rebuilt"
        refresh.active = True
        self._resolve_absent_deficiencies(db, refresh, rebuilt)
        db.commit()
        return rebuilt

    @staticmethod
    def _resolve_absent_deficiencies(db: Session, refresh: ContextRefreshRequest, context: IntelligenceContext) -> None:
        remaining = {item.fingerprint for item in context.deficiencies}
        for deficiency_id in json.loads(refresh.deficiency_ids_json or "[]"):
            row = db.get(ContextDeficiencyRecord, deficiency_id)
            if row and row.fingerprint not in remaining:
                row.status = "resolved"
                row.resolved_at = datetime.now(UTC)

    @staticmethod
    def persist_receipt(db: Session, user: User, context: IntelligenceContext) -> IntelligenceContextReceiptRecord:
        receipt = IntelligenceContextReceiptRecord(
            user_id=user.id,
            context_id=context.context_id,
            contract_version=context.contract_version,
            content_hash=context.receipt.content_hash,
            receipt_json=_json(context.receipt),
        )
        db.add(receipt)
        db.flush()
        return receipt
