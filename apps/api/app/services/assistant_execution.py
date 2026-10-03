"""API-owned background executions. Run a single local API process (two slots)."""

import asyncio
import hashlib
import json
import time
from uuid import uuid4
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
    row = db.scalar(
        select(AssistantExecution).where(
            AssistantExecution.id == identifier, AssistantExecution.user_id == user_id
        )
    )
    if row is None:
        raise HTTPException(404, "Assistant execution not found")
    return row


def completed_final_turn(row):
    if not row.transcript_encrypted:
        return False
    checkpoint = json.loads(decrypt_secret(row.transcript_encrypted))
    turns = checkpoint.get("turns", [])
    return bool(checkpoint.get("provider_turn_complete") and turns
                and turns[-1].get("role") == "assistant"
                and not any(block.get("type") == "tool_call" for block in turns[-1].get("content", [])))


def queue_finalization_recovery(db, user_id, identifier):
    """Explicit local recovery only; never schedule another external attempt."""
    row = owned(db, user_id, identifier)
    if row.status != "failed" or row.error_code not in {
        "response_serialization_failed", "response_rendering_failed", "response_persistence_failed",
        "TypeError",  # historical timestamp/compact-result failures
    } or not completed_final_turn(row):
        raise HTTPException(409, "No completed final turn available for local recovery")
    uncertain = db.scalar(select(AssistantAttempt.id).where(
        AssistantAttempt.execution_id == row.id,
        AssistantAttempt.status.in_(["sent", "uncertain"]),
    ))
    if uncertain:
        raise HTTPException(409, "Uncertain provider attempt cannot be recovered")
    row.status = "queued"
    row.error_code = None
    row.completed_at = None
    row.heartbeat_at = None
    db.commit()
    return row.id


def accept(db, user, payload, client_request_id, conversation_id=None):
    from app.ai.orchestrator import _conversation, _resolved_portfolio

    raw = json.dumps(
        {"payload": payload.model_dump(), "conversation_id": conversation_id}, sort_keys=True
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()
    existing = db.scalar(
        select(AssistantExecution).where(
            AssistantExecution.user_id == user.id,
            AssistantExecution.client_request_id == client_request_id,
        )
    )
    if existing:
        if existing.request_hash != digest:
            raise HTTPException(409, "Client request ID was already used with different content")
        return existing
    context = payload.page_context
    if context:
        if context.page == "portfolio" and not context.portfolio_id:
            raise HTTPException(422, "Portfolio page requires a portfolio")
        if context.page == "company" and not context.instrument_id:
            raise HTTPException(422, "Company page requires a company")
        payload = payload.model_copy(update={"portfolio_id": context.portfolio_id if context.page == "portfolio" else None,
                                             "instrument_id": context.instrument_id if context.page == "company" else None})
    conversation = _conversation(db, user, conversation_id, payload)
    db.refresh(conversation, with_for_update=True)
    active = db.scalar(select(AssistantExecution.id).where(AssistantExecution.conversation_id == conversation.id,
                         AssistantExecution.status.in_(["queued", "running"])))
    if active:
        raise HTTPException(409, "This conversation is already generating")
    if payload.company_only and payload.portfolio_id:
        raise HTTPException(422, "Company-only analysis cannot select a portfolio")
    portfolio = None if payload.company_only else _resolved_portfolio(db, user, conversation, payload.portfolio_id)
    if portfolio is not None:
        payload = payload.model_copy(update={"portfolio_id": portfolio.id})
        conversation.portfolio_id = portfolio.id
    from app.models.workstation import Instrument
    from app.services.assistant_policy import selected_policy
    instrument = db.get(Instrument, payload.instrument_id) if payload.instrument_id else None
    if payload.instrument_id and instrument is None:
        raise HTTPException(404, "Company not found")
    resolved_context = {"page": context.page if context else "workspace",
                        "instrument_id": instrument.id if instrument else None,
                        "symbol": instrument.symbol if instrument else None,
                        "company_name": instrument.name if instrument else None,
                        "portfolio_id": portfolio.id if portfolio else None,
                        "portfolio_name": portfolio.name if portfolio else None}
    identifier = str(uuid4())
    db.add(AssistantMessage(conversation_id=conversation.id, role="user", content=payload.question,
                           execution_id=identifier, context_json=json.dumps(resolved_context)))
    row = AssistantExecution(
        id=identifier, policy_json=json.dumps(selected_policy()),
        user_id=user.id,
        client_request_id=client_request_id,
        request_hash=digest,
        request_encrypted=encrypt_secret(payload.model_dump_json()),
        conversation_id=conversation.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(AssistantExecution).where(
                AssistantExecution.user_id == user.id,
                AssistantExecution.client_request_id == client_request_id,
            )
        )
        if existing is None:
            raise HTTPException(409, "This conversation is already generating")
        if existing.request_hash != digest:
            raise HTTPException(409, "Client request ID was already used with different content")
        return existing
    db.refresh(row)
    return row


async def _heartbeat(identifier):
    while True:
        await asyncio.sleep(10)
        with SessionLocal.begin() as db:
            db.execute(
                update(AssistantExecution)
                .where(AssistantExecution.id == identifier, AssistantExecution.status == "running")
                .values(heartbeat_at=now())
            )


async def execute(identifier):
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(2)
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=settings.assistant_queue_timeout_seconds)
    except TimeoutError:
        from app.services import assistant_events as events
        with SessionLocal.begin() as db:
            row = db.get(AssistantExecution, identifier)
            if row.status != "queued":
                return
            row.status = "timeout"
            row.error_code = "execution_queue_timeout"
            row.completed_at = now()
            events.save_terminal_partial(db, row)
        events.append(identifier, "terminal", {"status": "timeout", "error_code": "execution_queue_timeout", "response": None})
        return
    try:
        await _execute_claimed(identifier)
    finally:
        _slots.release()


async def _execute_claimed(identifier):
    with SessionLocal.begin() as db:
        claimed = db.execute(
            update(AssistantExecution)
            .where(AssistantExecution.id == identifier, AssistantExecution.status == "queued")
            .values(
                status="running",
                started_at=func.coalesce(AssistantExecution.started_at, now()),
                heartbeat_at=now(),
            )
        )
        if claimed.rowcount != 1:
            return
    from app.services import assistant_events as events
    events.append(identifier, "activity", {"text": "Preparing context"})
    token = diagnostics.execution_id.set(identifier)
    heartbeat = asyncio.create_task(_heartbeat(identifier))
    try:
        from app.ai.orchestrator import run_assistant

        with SessionLocal() as db:
            row = db.get(AssistantExecution, identifier)
            payload = AssistantMessageCreate.model_validate_json(
                decrypt_secret(row.request_encrypted)
            )
            user = db.get(User, row.user_id)
            deadline = settings.assistant_execution_deadline_seconds
            elapsed = (now() - row.started_at.replace(tzinfo=now().tzinfo)).total_seconds()
            local_finalization = completed_final_turn(row)
            if elapsed >= deadline and not local_finalization:
                from app.ai.tool_loop import AssistantTerminalError

                raise AssistantTerminalError("execution_deadline_exhausted")
            stage_id = diagnostics.begin_stage("orchestration")
            stage_started = time.perf_counter()
            try:
                async with asyncio.timeout(None if local_finalization else deadline - elapsed + settings.assistant_queue_timeout_seconds * 7):
                    result = await run_assistant(
                        db, user, payload, row.conversation_id, accepted=True
                    )
            except BaseException as exc:
                diagnostics.finish_stage(
                    stage_id,
                    status="failed",
                    error=exc,
                    latency_ms=round((time.perf_counter() - stage_started) * 1000),
                )
                if isinstance(exc, TimeoutError):
                    from app.ai.tool_loop import AssistantTerminalError

                    raise AssistantTerminalError("execution_deadline_exhausted") from exc
                raise
            else:
                diagnostics.finish_stage(
                    stage_id,
                    status="completed",
                    latency_ms=round((time.perf_counter() - stage_started) * 1000),
                )
            terminal_error_code = result.pop("_terminal_error_code", None)
            result["synthesis"]["execution_id"] = identifier
            serialized = AssistantResponse.model_validate(result).model_dump_json()
        persistence_stage_id = diagnostics.begin_stage("response_persistence")
        persistence_started = time.perf_counter()
        try:
            with SessionLocal.begin() as db:
                row = db.get(AssistantExecution, identifier)
                row.response_json = serialized
                unavailable = result.get("synthesis", {}).get("mode") == "synthesis_unavailable"
                row.status = ("incomplete" if terminal_error_code == "output_truncated" else "limited" if terminal_error_code == "question_budget_exhausted" else "synthesis_unavailable") if unavailable else "completed"
                row.error_code = terminal_error_code
                row.completed_at = now()
        except BaseException as exc:
            diagnostics.finish_stage(
                persistence_stage_id,
                status="failed",
                error=exc,
                latency_ms=round((time.perf_counter() - persistence_started) * 1000),
            )
            from app.ai.tool_loop import AssistantTerminalError

            raise AssistantTerminalError("response_persistence_failed") from exc
        else:
            diagnostics.finish_stage(
                persistence_stage_id,
                status="completed",
                latency_ms=round((time.perf_counter() - persistence_started) * 1000),
            )
    except asyncio.CancelledError:
        with SessionLocal.begin() as db:
            row = db.get(AssistantExecution, identifier)
            # Shutdown is an uncertain restart, not a user stop. Leave it for reconciliation.
            if row.cancel_requested_at:
                row.status = "stopped"
                row.error_code = "user_stopped"
                row.completed_at = now()
        raise
    except Exception as exc:
        with SessionLocal.begin() as db:
            row = db.get(AssistantExecution, identifier)
            row.status = "timeout" if getattr(exc, "code", "") in {"execution_deadline_exhausted", "provider_timeout", "provider_queue_timeout"} or isinstance(exc, TimeoutError) else "failed"
            row.error_code = (
                f"http_{exc.status_code}"
                if isinstance(exc, HTTPException)
                else getattr(exc, "code", type(exc).__name__)
            )
            row.completed_at = now()
    finally:
        with SessionLocal.begin() as db:
            row = db.get(AssistantExecution, identifier)
            if row.completed_at:
                if not row.response_json and row.error_code != "response_persistence_failed":
                    events.save_terminal_partial(db, row)
                final_status, final_error, final_response = row.status, row.error_code, row.response_json
                db.execute(update(AssistantMessage).where(AssistantMessage.execution_id == identifier).values(outcome=final_status))
            else:
                final_status = None
        if final_status:
            events.append(identifier, "terminal", {"status": final_status, "error_code": final_error,
                          "response": json.loads(final_response) if final_response else None})
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
        task.add_done_callback(
            lambda completed: _tasks.pop(identifier, None)
            if _tasks.get(identifier) is completed
            else None
        )


def reconcile(db):
    """Restart safe local work and fail closed on uncertain external attempts."""
    cutoff = now() - timedelta(seconds=30)
    rows = db.scalars(
        select(AssistantExecution).where(AssistantExecution.status.in_(["queued", "running"]))
    )
    ready = []
    for row in rows:
        if (
            row.status == "running"
            and row.heartbeat_at
            and row.heartbeat_at.replace(tzinfo=cutoff.tzinfo) > cutoff
        ):
            continue
        attempts = list(
            db.scalars(select(AssistantAttempt).where(AssistantAttempt.execution_id == row.id))
        )
        uncertain = [attempt for attempt in attempts if attempt.status == "sent"]
        for attempt in uncertain:
            attempt.status = "uncertain"
            metadata = json.loads(attempt.metadata_json)
            metadata["possible_duplicate_charge"] = True
            attempt.metadata_json = json.dumps(metadata)
        paid_uncertain = [attempt for attempt in uncertain if attempt.provider != "mock"]
        if paid_uncertain:
            row.status = "interrupted"
            row.error_code = "provider_attempt_uncertain"
            row.completed_at = now()
            from app.services.assistant_events import save_terminal_partial
            save_terminal_partial(db, row)
        elif uncertain and row.retry_count >= 1:
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
            from app.services.assistant_events import prune
            prune(db)
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


def cancel(db, user_id, identifier):
    row = owned(db, user_id, identifier)
    if row.status not in {"queued", "running"}:
        return row.status
    from app.services import assistant_events as events
    batch = events._batches.get(identifier)
    if batch:
        batch.flush()
    row.cancel_requested_at = now()
    row.status = "stopped"
    row.error_code = "user_stopped"
    row.completed_at = now()
    events.save_terminal_partial(db, row)
    db.execute(update(AssistantMessage).where(AssistantMessage.execution_id == identifier).values(outcome="stopped"))
    db.commit()
    task = _tasks.get(identifier)
    if task and not task.done():
        task.cancel()
    from app.services.assistant_events import append
    append(identifier, "terminal", {"status": "stopped", "error_code": "user_stopped", "response": None})
    return "stopped"
