"""API-owned background executions. Run a single local API process (two slots)."""
import asyncio
import hashlib
import json
import time
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, update, func
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.security import encrypt_secret, decrypt_secret
from app.db.session import SessionLocal
from app.models.assistant_execution import AssistantExecution, AssistantAttempt, now
from app.models.user import User
from app.models.workstation import AssistantMessage
from app.schemas.assistant import AssistantMessageCreate, AssistantResponse
from app.services import assistant_diagnostics as diagnostics

_tasks: dict[str, asyncio.Task] = {}
_slots: asyncio.Semaphore | None = None


def owned(db, user_id, identifier):
    row = db.scalar(select(AssistantExecution).where(
        AssistantExecution.id == identifier, AssistantExecution.user_id == user_id))
    if row is None:
        raise HTTPException(404, "Assistant execution not found")
    return row


def accept(db, user, payload, client_request_id, conversation_id=None):
    from app.ai.orchestrator import _conversation, _resolved_portfolio
    raw = json.dumps({"payload": payload.model_dump(), "conversation_id": conversation_id}, sort_keys=True)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    existing = db.scalar(select(AssistantExecution).where(
        AssistantExecution.user_id == user.id,
        AssistantExecution.client_request_id == client_request_id))
    if existing:
        if existing.request_hash != digest:
            raise HTTPException(409, "Client request ID was already used with different content")
        return existing
    conversation = _conversation(db, user, conversation_id, payload)
    portfolio = _resolved_portfolio(db, user, conversation, payload.portfolio_id)
    if portfolio is not None:
        payload = payload.model_copy(update={"portfolio_id": portfolio.id})
        conversation.portfolio_id = portfolio.id
    db.add(AssistantMessage(conversation_id=conversation.id, role="user", content=payload.question))
    row = AssistantExecution(user_id=user.id, client_request_id=client_request_id,
        request_hash=digest, request_encrypted=encrypt_secret(payload.model_dump_json()),
        conversation_id=conversation.id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(AssistantExecution).where(
            AssistantExecution.user_id == user.id,
            AssistantExecution.client_request_id == client_request_id))
        if existing is None:
            raise
        if existing.request_hash != digest:
            raise HTTPException(409, "Client request ID was already used with different content")
        return existing
    db.refresh(row)
    return row


async def _heartbeat(identifier):
    while True:
        await asyncio.sleep(10)
        with SessionLocal.begin() as db:
            db.execute(update(AssistantExecution).where(
                AssistantExecution.id == identifier, AssistantExecution.status == "running"
            ).values(heartbeat_at=now()))


async def execute(identifier):
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(2)
    async with _slots:
        with SessionLocal.begin() as db:
            claimed = db.execute(update(AssistantExecution).where(
                AssistantExecution.id == identifier, AssistantExecution.status == "queued"
            ).values(status="running", started_at=func.coalesce(AssistantExecution.started_at, now()), heartbeat_at=now()))
            if claimed.rowcount != 1:
                return
        token = diagnostics.execution_id.set(identifier)
        heartbeat = asyncio.create_task(_heartbeat(identifier))
        try:
            from app.ai.orchestrator import run_assistant
            with SessionLocal() as db:
                row = db.get(AssistantExecution, identifier)
                payload = AssistantMessageCreate.model_validate_json(decrypt_secret(row.request_encrypted))
                user = db.get(User, row.user_id)
                deadline = settings.phase8_targeted_deadline_seconds
                from app.ai.orchestrator import MARKET_DISCOVERY_RE
                if MARKET_DISCOVERY_RE.search(payload.question):
                    deadline = settings.phase8_market_deadline_seconds
                elif payload.instrument_id or any(word in payload.question.lower() for word in ("compare", "how much", "switch", "buy", "sell")):
                    deadline = settings.phase8_sizing_deadline_seconds
                elapsed = (now() - row.started_at.replace(tzinfo=now().tzinfo)).total_seconds()
                if elapsed >= deadline:
                    raise TimeoutError("execution_deadline_exhausted")
                stage_id = diagnostics.begin_stage("orchestration")
                stage_started = time.perf_counter()
                try:
                    async with asyncio.timeout(deadline - elapsed):
                        result = await run_assistant(
                            db, user, payload, row.conversation_id, accepted=True
                        )
                except BaseException:
                    diagnostics.finish_stage(
                        stage_id,
                        status="failed",
                        latency_ms=round((time.perf_counter() - stage_started) * 1000),
                    )
                    raise
                else:
                    diagnostics.finish_stage(
                        stage_id,
                        status="completed",
                        latency_ms=round((time.perf_counter() - stage_started) * 1000),
                    )
                result["synthesis"]["execution_id"] = identifier
                serialized = AssistantResponse.model_validate(result).model_dump_json()
            persistence_stage_id = diagnostics.begin_stage("response_persistence")
            persistence_started = time.perf_counter()
            try:
                with SessionLocal.begin() as db:
                    row = db.get(AssistantExecution, identifier)
                    row.response_json = serialized
                    unavailable = (
                        result.get("synthesis", {}).get("mode")
                        == "recommendation_synthesis_unavailable"
                    )
                    row.status = "synthesis_unavailable" if unavailable else "completed"
                    row.completed_at = now()
            except BaseException:
                diagnostics.finish_stage(
                    persistence_stage_id,
                    status="failed",
                    latency_ms=round((time.perf_counter() - persistence_started) * 1000),
                )
                raise
            else:
                diagnostics.finish_stage(
                    persistence_stage_id,
                    status="completed",
                    latency_ms=round((time.perf_counter() - persistence_started) * 1000),
                )
        except Exception as exc:
            with SessionLocal.begin() as db:
                row = db.get(AssistantExecution, identifier)
                row.status = "failed"
                row.error_code = f"http_{exc.status_code}" if isinstance(exc, HTTPException) else type(exc).__name__
                row.completed_at = now()
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            diagnostics.execution_id.reset(token)
            with SessionLocal.begin() as db:
                diagnostics.cleanup(db, settings.phase8_diagnostic_payload_bytes)


def schedule(identifier):
    task = _tasks.get(identifier)
    if task is None or task.done():
        task = asyncio.create_task(execute(identifier))
        _tasks[identifier] = task
        task.add_done_callback(lambda completed: _tasks.pop(identifier, None)
                               if _tasks.get(identifier) is completed else None)


def reconcile(db):
    """Startup recovery fails closed after an uncertain paid attempt.

    Safe computations are restarted; no completed evidence is reused across versions.
    Sent attempts without outcomes consume the one durable retry allowance.
    """
    cutoff = now() - timedelta(seconds=30)
    rows = db.scalars(select(AssistantExecution).where(
        AssistantExecution.status.in_(["queued", "running"])))
    ready = []
    for row in rows:
        if row.status == "running" and row.heartbeat_at and row.heartbeat_at.replace(tzinfo=cutoff.tzinfo) > cutoff:
            continue
        attempts = list(db.scalars(select(AssistantAttempt).where(AssistantAttempt.execution_id == row.id)))
        uncertain = [attempt for attempt in attempts if attempt.status == "sent"]
        for attempt in uncertain:
            attempt.status = "uncertain"
            metadata = json.loads(attempt.metadata_json)
            metadata["possible_duplicate_charge"] = True
            attempt.metadata_json = json.dumps(metadata)
        if uncertain and row.retry_count >= 1:
            row.status = "failed"
            row.error_code = "provider_retry_exhausted"
            row.completed_at = now()
        else:
            if uncertain:
                row.retry_count += 1
            row.status = "queued"
            ready.append(row.id)
    db.commit()
    return ready


async def maintenance():
    while True:
        with SessionLocal() as db:
            for identifier in reconcile(db):
                schedule(identifier)
            diagnostics.cleanup(db, settings.phase8_diagnostic_payload_bytes)
            db.commit()
        await asyncio.sleep(20)


async def shutdown():
    global _slots
    tasks = list(_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _tasks.clear()
    _slots = None
