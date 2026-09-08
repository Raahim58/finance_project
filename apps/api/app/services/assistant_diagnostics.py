"""Private encrypted payloads; inspection/export use a structural allowlist only."""
import hashlib
import json
from contextvars import ContextVar
from datetime import timedelta

from sqlalchemy import select, delete
from app.core.config import settings
from app.core.security import encrypt_secret, decrypt_secret
from app.db.session import SessionLocal
from app.models.assistant_execution import AssistantExecution, AssistantAttempt, AssistantStage, now
from app.models.llm_invocation import LLMInvocation

execution_id: ContextVar[str | None] = ContextVar("assistant_execution_id", default=None)
SAFE_FIELDS = {"input_bytes", "estimated_input_tokens", "input_tokens", "output_tokens",
               "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "latency_ms",
               "projection_version", "schema_version", "prompt_version", "code_version",
               "error_code", "possible_duplicate_charge", "finish_reason",
               "estimated_cost", "pricing_version", "selected_evidence_count",
               "omitted_evidence_count", "evidence_version_hash",
               "portfolio_version_hash", "ips_version_hash", "analytical_method_version"}


def _structural_context_metadata(messages):
    metadata = {
        "code_version": "phase8-revamp-1",
        "analytical_method_version": "verified-allocation-1",
        "selected_evidence_count": 0,
        "omitted_evidence_count": 0,
    }
    try:
        payload = json.loads(messages[-1]["content"])
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        return metadata
    version_values = {"evidence": [], "portfolio": [], "ips": []}

    def walk(value):
        if isinstance(value, dict):
            counts = value.get("counts")
            if value.get("projection_version") and isinstance(counts, dict):
                metadata["selected_evidence_count"] += int(counts.get("unique_records", 0))
                metadata["omitted_evidence_count"] += int(counts.get("omitted_evidence", 0))
            for key, child in value.items():
                lowered = key.lower()
                if child is not None and key in {"evidence_id", "content_hash"}:
                    version_values["evidence"].append(str(child))
                elif child is not None and key == "portfolio_id":
                    version_values["portfolio"].append(str(child))
                elif child is not None and key == "ips_version_id":
                    version_values["ips"].append(str(child))
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    for name, values in version_values.items():
        if values:
            metadata[f"{name}_version_hash"] = hashlib.sha256(
                json.dumps(sorted(set(values))).encode()
            ).hexdigest()
    return metadata


def sampled(identifier: str) -> bool:
    return int(hashlib.sha256(identifier.encode()).hexdigest(), 16) % 10 == 0


def begin_attempt(operation, provider, model, messages, estimated_tokens):
    identifier = execution_id.get()
    if identifier is None:
        return None
    # Encrypt before recording a sent attempt. Failure prevents the provider call.
    encrypted = encrypt_secret(json.dumps({"messages": messages}))
    with SessionLocal.begin() as db:
        execution = db.get(AssistantExecution, identifier, with_for_update=True)
        if operation == "mechanical_repair":
            if execution.repair_count >= 1:
                raise ValueError("format_repair_exhausted")
            execution.repair_count += 1
        if operation == "allocation_revision":
            if execution.revision_count >= 1:
                raise ValueError("allocation_revision_exhausted")
            execution.revision_count += 1
        payload = json.loads(decrypt_secret(execution.request_encrypted))
        first = db.scalar(select(AssistantAttempt).where(AssistantAttempt.execution_id == identifier)
                          .order_by(AssistantAttempt.created_at).limit(1))
        if first and (first.provider != provider or first.model != model):
            raise ValueError("provider_model_changed_during_execution")
        if not first:
            payload.update(provider=provider, model=model)
            execution.request_encrypted = encrypt_secret(json.dumps(payload))
        from app.reasoning.planning import classify
        plan = classify(payload["question"], bool(payload.get("instrument_id")))
        if execution.reserved_input_tokens + estimated_tokens > plan.execution_input:
            raise ValueError("execution_input_budget_exhausted")
        capacity = cleanup(db, settings.phase8_diagnostic_payload_bytes)
        if (
            capacity["retained_payload_bytes"] + len(encrypted.encode())
            > settings.phase8_diagnostic_payload_bytes
        ):
            raise ValueError("diagnostic_payload_capacity_exhausted")
        execution.reserved_input_tokens += estimated_tokens
        attempt_metadata = {
            "estimated_input_tokens": estimated_tokens,
            "input_bytes": len(json.dumps(messages).encode()),
            "projection_version": "phase8-projection-1",
            "schema_version": "phase8-answer-1",
            "prompt_version": "phase8-1",
            **_structural_context_metadata(messages),
        }
        row = AssistantAttempt(execution_id=identifier, operation=operation,
            provider=provider, model=model, payload_encrypted=encrypted,
            metadata_json=json.dumps(attempt_metadata))
        db.add(row)
        db.flush()
        return row.id


def finish_attempt(identifier, *, response=None, error=None, latency_ms=0):
    if identifier is None:
        return
    with SessionLocal.begin() as db:
        row = db.get(AssistantAttempt, identifier)
        metadata = json.loads(row.metadata_json)
        metadata["latency_ms"] = latency_ms
        if response is not None:
            metadata.update({key: getattr(response, key, None) for key in (
                "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                "reasoning_tokens", "finish_reason")})
            payload = json.loads(decrypt_secret(row.payload_encrypted))
            payload["response"] = response.content
            row.payload_encrypted = encrypt_secret(json.dumps(payload))
            row.status = "completed"
            try:
                pricing = json.loads(settings.phase8_pricing_json or "{}")
            except json.JSONDecodeError:
                pricing = {}
            rates = pricing.get(f"{row.provider}:{row.model}") or pricing.get(row.provider)
            if isinstance(rates, dict) and all(
                isinstance(rates.get(key), (int, float))
                for key in ("input_per_million", "output_per_million")
            ) and response.input_tokens is not None and response.output_tokens is not None:
                metadata["estimated_cost"] = round(
                    response.input_tokens * rates["input_per_million"] / 1_000_000
                    + response.output_tokens * rates["output_per_million"] / 1_000_000,
                    8,
                )
                metadata["pricing_version"] = settings.phase8_pricing_version
        else:
            # Exception messages and provider bodies may echo private input or secrets.
            metadata["error_code"] = type(error).__name__
            row.status = "failed"
        row.metadata_json = json.dumps(metadata)
        row.completed_at = now()


def inspect_execution(db, execution):
    attempts = db.scalars(select(AssistantAttempt).where(
        AssistantAttempt.execution_id == execution.id).order_by(AssistantAttempt.created_at))
    queue_ms = None
    if execution.started_at:
        queue_ms = round(
            (execution.started_at.replace(tzinfo=now().tzinfo)
             - execution.created_at.replace(tzinfo=now().tzinfo)).total_seconds() * 1000
        )
    return {"id": execution.id, "status": execution.status, "created_at": execution.created_at,
        "started_at": execution.started_at, "completed_at": execution.completed_at,
        "received_at": execution.received_at, "error_code": execution.error_code,
        "queue_ms": queue_ms,
        "retry_count": execution.retry_count, "repair_count": execution.repair_count,
        "revision_count": execution.revision_count,
        "reserved_input_tokens": execution.reserved_input_tokens,
        "stages": [{"id": stage.id, "operation": stage.operation, "status": stage.status,
                    "created_at": stage.created_at, "completed_at": stage.completed_at,
                    "metadata": json.loads(stage.metadata_json)}
                   for stage in db.scalars(select(AssistantStage).where(AssistantStage.execution_id == execution.id))],
        "attempts": [{"id": row.id, "operation": row.operation, "provider": row.provider,
            "status": row.status, "created_at": row.created_at, "completed_at": row.completed_at,
            "payload_eviction": row.payload_eviction,
            "metadata": {key: value for key, value in json.loads(row.metadata_json).items()
                         if key in SAFE_FIELDS}} for row in attempts]}


def cleanup(db, ceiling_bytes=1024 ** 3):
    current = now()
    rows = list(db.execute(select(AssistantAttempt, AssistantExecution.status).join(
        AssistantExecution, AssistantExecution.id == AssistantAttempt.execution_id)
        .order_by(AssistantAttempt.created_at)))
    retained = []
    for row, status in rows:
        created = row.created_at.replace(tzinfo=current.tzinfo)
        reason = None
        if created < current - timedelta(days=14):
            reason = "expired"
        elif status == "completed" and not sampled(row.execution_id):
            reason = "unsampled_success"
        if reason and row.payload_encrypted:
            row.payload_encrypted = None
            row.payload_eviction = reason
        if row.payload_encrypted:
            retained.append((row, status))
    total = sum(len(row.payload_encrypted.encode()) for row, _ in retained)
    # In-flight attempts must remain diagnosable. Fail closed on subsequent writes if
    # active payloads alone exceed capacity; never remove their accounting records.
    for row, status in sorted(retained, key=lambda item: item[1] != "completed"):
        if total <= ceiling_bytes:
            break
        if status in {"queued", "running"}:
            continue
        total -= len(row.payload_encrypted.encode())
        row.payload_encrypted = None
        row.payload_eviction = "capacity"
    db.execute(delete(AssistantStage).where(AssistantStage.created_at < current - timedelta(days=365)).execution_options(synchronize_session=False))
    db.execute(delete(AssistantAttempt).where(AssistantAttempt.created_at < current - timedelta(days=365)).execution_options(synchronize_session=False))
    expired_executions = select(AssistantExecution.id).where(
        AssistantExecution.created_at < current - timedelta(days=365)
    )
    db.execute(delete(LLMInvocation).where(
        LLMInvocation.execution_id.in_(expired_executions)
    ).execution_options(synchronize_session=False))
    db.execute(delete(AssistantExecution).where(
        AssistantExecution.id.in_(expired_executions)
    ).execution_options(synchronize_session=False))
    db.flush()
    return {"retained_payload_bytes": total, "capacity_exceeded": total > ceiling_bytes}


def recovered_response(operation, provider, model, messages):
    """Reuse only byte-identical stage input including current evidence/version references."""
    identifier = execution_id.get()
    if identifier is None:
        return None
    from app.ai.providers.base import LLMProviderResult
    with SessionLocal() as db:
        rows = db.scalars(select(AssistantAttempt).where(
            AssistantAttempt.execution_id == identifier, AssistantAttempt.operation == operation,
            AssistantAttempt.provider == provider, AssistantAttempt.model == model,
            AssistantAttempt.status == "completed").order_by(AssistantAttempt.created_at.desc()))
        for row in rows:
            if not row.payload_encrypted:
                continue
            payload = json.loads(decrypt_secret(row.payload_encrypted))
            if payload.get("messages") == messages and isinstance(payload.get("response"), str):
                metadata = json.loads(row.metadata_json)
                return LLMProviderResult(content=payload["response"], provider=provider, model=model,
                    **{key: metadata.get(key) for key in ("input_tokens", "output_tokens",
                    "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "finish_reason")})
    return None


def consume_retry():
    identifier = execution_id.get()
    if identifier is None:
        return False
    with SessionLocal.begin() as db:
        row = db.get(AssistantExecution, identifier, with_for_update=True)
        if row.retry_count >= 1:
            return False
        row.retry_count += 1
        return True


def begin_stage(operation):
    from app.models.assistant_execution import AssistantStage
    identifier = execution_id.get()
    if identifier is None:
        return None
    with SessionLocal.begin() as db:
        row = AssistantStage(execution_id=identifier, operation=operation)
        db.add(row)
        db.flush()
        return row.id


def finish_stage(identifier, *, status, latency_ms, validation_count=0):
    from app.models.assistant_execution import AssistantStage
    if identifier is None:
        return
    with SessionLocal.begin() as db:
        row = db.get(AssistantStage, identifier)
        row.status = status
        row.completed_at = now()
        row.metadata_json = json.dumps({"latency_ms": latency_ms, "validation_failure_count": validation_count})
