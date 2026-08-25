"""Production coordinator linking context deficiencies to existing ingestion machinery."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.jobs.evidence_tasks import targeted_refresh
from app.jobs.phase2_tasks import (
    broad_fundamentals,
    dps_history,
    financial_download_catalog,
    financial_extract,
)
from app.models.document import Document
from app.models.evidence import EvidenceRefreshRequest
from app.models.intelligence_context import ContextDeficiencyRecord, ContextIngestionWork
from app.models.workstation import (
    FinancialFact,
    IngestionCoverage,
    IngestionRun,
    Instrument,
    StandardizedFinancialFact,
)
from app.schemas.intelligence_context import ContextDeficiency, IngestionWorkReference
from app.services.context_deficiency_bridge import (
    ContextIngestionRouter,
    IngestionRoute,
    TERMINAL_STATES,
)
from app.services.coverage_service import coverage, is_queueable, reserve_and_publish
from app.services.macro_schedule_service import enqueue_due_macro_refreshes
from app.services.phase2_orchestration import incremental_catalog_dispatch_key


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _month_keys(start: date, end: date):
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        yield cursor.year, cursor.month
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)


class DatabaseIngestionCoordinator:
    """Select and track existing durable jobs without exposing them to callers."""

    def __init__(
        self,
        db: Session,
        *,
        user_id: str,
        router: ContextIngestionRouter | None = None,
        now=None,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.router = router or ContextIngestionRouter()
        self.now = now or (lambda: datetime.now(UTC))

    def schedule(self, deficiency: ContextDeficiency) -> IngestionWorkReference:
        route = self.router.decide(deficiency)
        if not route.actionable:
            return IngestionWorkReference(
                work_id=f"not_applicable:{deficiency.fingerprint}",
                state="not_applicable",
                coordinator=type(self).__name__,
            )
        record = self.db.scalar(select(ContextDeficiencyRecord).where(
            ContextDeficiencyRecord.fingerprint == deficiency.fingerprint
        ))
        if record is None:
            raise RuntimeError("Deficiency must be persisted before ingestion is scheduled")
        work = self.db.scalar(select(ContextIngestionWork).where(
            ContextIngestionWork.deficiency_id == record.id
        ).with_for_update())
        if work and work.status not in TERMINAL_STATES:
            return self._reference(work)
        now = self.now()
        if work is None:
            dialect = self.db.get_bind().dialect.name
            factory = (
                postgresql_insert if dialect == "postgresql"
                else sqlite_insert if dialect == "sqlite"
                else None
            )
            if factory is not None:
                work_id = str(uuid4())
                inserted_id = self.db.scalar(
                    factory(ContextIngestionWork).values(
                        id=work_id,
                        deficiency_id=record.id,
                        family=route.family or "",
                        mode=route.mode or "",
                        status="queued",
                        linked_work_json="[]",
                        attempt_count=1,
                        requested_at=now,
                        deadline_at=now + self._timeout(route),
                        updated_at=now,
                    ).on_conflict_do_nothing(
                        index_elements=[ContextIngestionWork.deficiency_id]
                    ).returning(ContextIngestionWork.id)
                )
                work = self.db.get(
                    ContextIngestionWork, inserted_id or work_id, populate_existing=True
                ) if inserted_id else self.db.scalar(select(ContextIngestionWork).where(
                    ContextIngestionWork.deficiency_id == record.id
                ).with_for_update())
                if inserted_id is None:
                    if work is None:
                        raise RuntimeError("Concurrent ingestion work could not be resolved")
                    return self._reference(work)
            else:
                work = ContextIngestionWork(
                    deficiency_id=record.id,
                    family=route.family or "",
                    mode=route.mode or "",
                    deadline_at=now + self._timeout(route),
                )
                self.db.add(work)
                self.db.flush()
        else:
            work.family = route.family or ""
            work.mode = route.mode or ""
            work.status = "queued"
            work.attempt_count += 1
            work.error_message = None
            work.requested_at = now
            work.deadline_at = now + self._timeout(route)
            work.terminal_at = None
        try:
            links = self._dispatch(deficiency, route, now)
            work.linked_work_json = _json(links)
            work.status = self._aggregate(links, work)
        except Exception as exc:
            work.status = "failed"
            work.error_message = f"{type(exc).__name__}: {str(exc)[:500]}"
            work.terminal_at = self.now()
        self.db.commit()
        return self._reference(work)

    def status(self, work_id: str) -> IngestionWorkReference:
        if work_id.startswith("not_applicable:"):
            return IngestionWorkReference(
                work_id=work_id,
                state="not_applicable",
                coordinator=type(self).__name__,
            )
        work = self.db.get(ContextIngestionWork, work_id, with_for_update=True)
        if work is None:
            return IngestionWorkReference(
                work_id=work_id, state="failed", coordinator=type(self).__name__
            )
        if work.status in TERMINAL_STATES:
            return self._reference(work)
        if self.now() >= _utc(work.deadline_at):
            work.status = "timed_out"
            work.error_message = "Linked ingestion did not reach a terminal state before its deadline."
            work.terminal_at = self.now()
            self.db.commit()
            return self._reference(work)
        links = json.loads(work.linked_work_json or "[]")
        links = self._expand_linked_work(work, links)
        work.linked_work_json = _json(links)
        work.status = self._aggregate(links, work)
        if work.status in TERMINAL_STATES:
            work.terminal_at = self.now()
        self.db.commit()
        return self._reference(work)

    @staticmethod
    def _timeout(route: IngestionRoute) -> timedelta:
        return timedelta(hours=24 if route.mode == "historical" else 4)

    @staticmethod
    def _reference(work: ContextIngestionWork) -> IngestionWorkReference:
        return IngestionWorkReference(
            work_id=work.id,
            state=work.status,
            coordinator="DatabaseIngestionCoordinator",
        )

    def _instrument(self, deficiency: ContextDeficiency) -> Instrument:
        row = self.db.scalar(select(Instrument).where(Instrument.symbol == deficiency.entity_key.upper()))
        if row is None:
            raise RuntimeError("Deficiency instrument is no longer present")
        return row

    def _dispatch(
        self, deficiency: ContextDeficiency, route: IngestionRoute, now: datetime
    ) -> list[dict[str, str]]:
        if route.family == "current_market":
            # The existing live scheduler polls independently. Link to its next durable run.
            return [{
                "kind": "scheduled_run",
                "job_key": f"refresh:{settings.market_data_mode}",
                "requested_after": now.isoformat(),
            }]
        instrument = self._instrument(deficiency)
        if route.family == "market_history":
            links = self._queue_history(instrument, now)
            links.append({
                "kind": "screening_snapshot",
                "instrument_id": instrument.id,
                "requested_after": now.isoformat(),
            })
            return links
        if route.family == "company_reports":
            return self._queue_company_reports(instrument, now)
        if route.family == "macro":
            result = enqueue_due_macro_refreshes(self.db, now=now)
            if result.status == "disabled":
                return [{"kind": "disabled", "reason": "macro_ingestion_disabled"}]
            return [{"kind": "ingestion_run", "id": run_id} for run_id in result.run_ids]
        if route.family == "evidence":
            return [self._queue_evidence(instrument, now)]
        raise RuntimeError(f"Unsupported ingestion family {route.family}")

    def _queue_history(self, instrument: Instrument, now: datetime) -> list[dict[str, str]]:
        end = now.date()
        start = end - timedelta(days=366)
        links: list[dict[str, str]] = []
        for year, month in _month_keys(start, end):
            period_key = f"{year:04d}-{month:02d}"
            row = coverage(self.db, instrument.id, "price_history", period_key, "dps")
            if is_queueable(row, now):
                reserve_and_publish(self.db, row, dps_history, (instrument.symbol, year, month), now)
            links.append({"kind": "coverage", "id": row.id})
        return links

    def _queue_company_reports(self, instrument: Instrument, now: datetime) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        broad = coverage(self.db, instrument.id, "standardized_fundamentals", "current", "dps")
        if is_queueable(broad, now, refresh_after=timedelta(days=30)):
            reserve_and_publish(self.db, broad, broad_fundamentals, (instrument.symbol,), now)
        links.append({"kind": "coverage", "id": broad.id})
        key = incremental_catalog_dispatch_key(now)
        catalog = coverage(
            self.db, instrument.id, "report_catalog_dispatch", key, "psx_financials"
        )
        if is_queueable(catalog, now):
            reserve_and_publish(
                self.db,
                catalog,
                financial_download_catalog,
                (instrument.symbol, "incremental", now.year, key),
                now,
            )
        links.append({"kind": "coverage", "id": catalog.id})
        return links

    def _queue_evidence(self, instrument: Instrument, now: datetime) -> dict[str, str]:
        request = EvidenceRefreshRequest(
            requested_by_user_id=self.user_id,
            request_type="targeted",
            scope_key=f"symbol:{instrument.symbol}",
            query_text=f'("{instrument.symbol}" OR "{instrument.name}") AND Pakistan',
            source_keys_json='["gdelt"]',
            status="queued",
            priority_class="live",
            max_candidates=25,
        )
        self.db.add(request)
        self.db.commit()
        request.status = "running"
        request.started_at = now
        self.db.commit()
        try:
            targeted_refresh.apply_async(
                args=(request.id,), queue="evidence_discovery", priority=0
            )
        except Exception as exc:
            # The evidence scheduler reconstructs queued requests from Postgres.
            request.status = "queued"
            request.error_class = type(exc).__name__
            request.error_message = str(exc)[:2000]
            self.db.commit()
        return {"kind": "evidence_request", "id": request.id}

    def _aggregate(self, links: list[dict[str, str]], work: ContextIngestionWork) -> str:
        states = [self._link_state(link, work) for link in links]
        if not states:
            return "partial"
        if any(state in {"queued", "running"} for state in states):
            return "running" if any(state == "running" for state in states) else "queued"
        if all(state == "succeeded" for state in states):
            if work.family == "company_reports" and not self._company_facts_available(work):
                return "partial"
            return "succeeded"
        if all(state == "failed" for state in states):
            return "failed"
        return "partial"

    def _work_instrument(self, work: ContextIngestionWork) -> Instrument | None:
        deficiency = self.db.get(ContextDeficiencyRecord, work.deficiency_id)
        return self.db.scalar(select(Instrument).where(
            Instrument.symbol == deficiency.entity_key.upper()
        )) if deficiency else None

    def _company_facts_available(self, work: ContextIngestionWork) -> bool:
        instrument = self._work_instrument(work)
        if instrument is None:
            return False
        filing = self.db.scalar(select(FinancialFact.id).where(
            FinancialFact.instrument_id == instrument.id
        ).limit(1))
        standardized = self.db.scalar(select(StandardizedFinancialFact.id).where(
            StandardizedFinancialFact.instrument_id == instrument.id,
            StandardizedFinancialFact.quality_status == "observed",
        ).limit(1))
        return bool(filing or standardized)

    def _expand_linked_work(
        self, work: ContextIngestionWork, links: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        if work.family != "company_reports":
            return links
        instrument = self._work_instrument(work)
        if instrument is None:
            return links
        linked_ids = {item.get("id") for item in links}
        for row in self.db.scalars(select(IngestionCoverage).where(
            IngestionCoverage.instrument_id == instrument.id,
            IngestionCoverage.dataset_type == "financial_report",
            IngestionCoverage.attempted_at >= work.requested_at,
        )):
            if row.id not in linked_ids:
                links.append({"kind": "coverage", "id": row.id})
                linked_ids.add(row.id)
        for document in self.db.scalars(select(Document).where(
            Document.symbol == instrument.symbol,
            Document.artifact_id.is_not(None),
            Document.downloaded_at >= work.requested_at,
        )):
            extraction = coverage(
                self.db, instrument.id, "financial_extract", document.id, "psx_financials"
            )
            if is_queueable(extraction, self.now()):
                reserve_and_publish(
                    self.db, extraction, financial_extract, (document.id,), self.now()
                )
            if extraction.id not in linked_ids:
                links.append({"kind": "coverage", "id": extraction.id})
                linked_ids.add(extraction.id)
        return links

    def _link_state(self, link: dict[str, str], work: ContextIngestionWork) -> str:
        kind = link["kind"]
        if kind == "disabled":
            return "failed"
        if kind == "coverage":
            row = self.db.get(IngestionCoverage, link["id"])
            if row is None:
                return "failed"
            if row.status == "complete":
                return "succeeded"
            if row.status == "partial":
                return "partial"
            if row.status == "failed" and row.retry_count >= settings.phase2_max_retries:
                return "failed"
            return "running" if row.status == "running" else "queued"
        if kind == "ingestion_run":
            row = self.db.get(IngestionRun, link["id"])
            if row is None or row.status == "failed":
                return "failed"
            if row.status == "completed":
                return "succeeded"
            if row.status == "partial":
                return "partial"
            return "running" if row.status == "running" else "queued"
        if kind == "evidence_request":
            row = self.db.get(EvidenceRefreshRequest, link["id"])
            if row is None or row.status == "failed":
                return "failed"
            if row.status == "complete":
                return "succeeded"
            if row.status == "partial":
                return "partial"
            return "running" if row.status in {"running", "processing"} else "queued"
        if kind == "scheduled_run":
            requested = datetime.fromisoformat(link["requested_after"])
            row = self.db.scalar(select(IngestionRun).where(
                IngestionRun.job_key == link["job_key"],
                IngestionRun.started_at >= requested,
            ).order_by(IngestionRun.started_at.desc()).limit(1))
            if row is None:
                return "queued"
            if row.status == "completed":
                return "succeeded"
            if row.status in {"partial"}:
                return "partial"
            if row.status == "failed":
                return "failed"
            return "running"
        if kind == "screening_snapshot":
            from app.models.workstation import CompanyScreeningSnapshot

            requested = datetime.fromisoformat(link["requested_after"])
            coverage_ids = [
                item["id"]
                for item in json.loads(work.linked_work_json or "[]")
                if item.get("kind") == "coverage"
            ]
            completed = [
                _utc(row.completed_at)
                for row in self.db.scalars(select(IngestionCoverage).where(
                    IngestionCoverage.id.in_(coverage_ids)
                ))
                if row.completed_at is not None
            ]
            if completed:
                requested = max(_utc(requested), max(completed))
            row = self.db.scalar(select(CompanyScreeningSnapshot).where(
                CompanyScreeningSnapshot.instrument_id == link["instrument_id"],
                CompanyScreeningSnapshot.computed_at >= requested,
            ).order_by(CompanyScreeningSnapshot.computed_at.desc()).limit(1))
            return "succeeded" if row else "queued"
        return "failed"
