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
SAFE_FIELDS = {
    "input_bytes",
    "transmitted_input_bytes",
    "retained_context_estimated_tokens",
    "accounted_input_tokens",
    "reservation_adjustment_tokens",
    "estimated_input_tokens",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "latency_ms",
    "projection_version",
    "schema_version",
    "prompt_version",
    "code_version",
    "error_code",
    "http_status",
    "error_type",
    "provider_message",
    "provider_request_id",
    "quota_violations",
    "retry_delay",
    "interaction_id",
    "web_tool_step_count",
    "web_citation_count",
    "possible_duplicate_charge",
    "finish_reason",
    "estimated_cost",
    "pricing_version",
    "selected_evidence_count",
    "omitted_evidence_count",
    "evidence_version_hash",
    "portfolio_version_hash",
    "ips_version_hash",
    "analytical_method_version",
}


def _structural_context_metadata(messages):
    metadata = {
        "code_version": "phase8-tool-loop-1",
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


def begin_attempt(
    operation,
    provider,
    model,
    messages,
    estimated_tokens,
    *,
    transmitted_input_bytes=None,
    schema_version="phase8-native-tool-turn-1",
):
    identifier = execution_id.get()
    if identifier is None:
        return None
    # Encrypt before recording a sent attempt. Failure prevents the provider call.
    encrypted = encrypt_secret(json.dumps({"messages": messages}))
    with SessionLocal.begin() as db:
        execution = db.get(AssistantExecution, identifier, with_for_update=True)
        payload = json.loads(decrypt_secret(execution.request_encrypted))
        first = db.scalar(
            select(AssistantAttempt)
            .where(AssistantAttempt.execution_id == identifier)
            .order_by(AssistantAttempt.created_at)
            .limit(1)
        )
        if first and (first.provider != provider or first.model != model):
            raise ValueError("provider_model_changed_during_execution")
        if not first:
            payload.update(provider=provider, model=model)
            execution.request_encrypted = encrypt_secret(json.dumps(payload))
        if (
            execution.reserved_input_tokens + estimated_tokens
            > settings.assistant_execution_input_token_limit
        ):
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
            "transmitted_input_bytes": transmitted_input_bytes,
            "retained_context_estimated_tokens": estimated_tokens,
            "projection_version": "phase8-tool-transcript-1",
            "schema_version": schema_version,
            "prompt_version": "phase8-tool-loop-1",
            **_structural_context_metadata(messages),
        }
        row = AssistantAttempt(
            execution_id=identifier,
            operation=operation,
            provider=provider,
            model=model,
            payload_encrypted=encrypted,
            metadata_json=json.dumps(attempt_metadata),
        )
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
            metadata.update(
                {
                    key: getattr(response, key, None)
                    for key in (
                        "input_tokens",
                        "output_tokens",
                        "cache_read_tokens",
                        "cache_write_tokens",
                        "reasoning_tokens",
                        "finish_reason",
                    )
                }
            )
            metadata["provider_request_id"] = response.request_id
            metadata["interaction_id"] = response.continuation_id
            metadata["web_tool_step_count"] = len(response.web_tool_activity)
            metadata["web_citation_count"] = len(response.web_citations)
            if response.transmitted_input_bytes is not None:
                metadata["transmitted_input_bytes"] = response.transmitted_input_bytes
            if response.input_tokens is not None:
                execution = db.get(
                    AssistantExecution, row.execution_id, with_for_update=True
                )
                reserved = int(metadata.get("estimated_input_tokens") or 0)
                adjustment = int(response.input_tokens) - reserved
                execution.reserved_input_tokens = max(
                    0, execution.reserved_input_tokens + adjustment
                )
                metadata["accounted_input_tokens"] = int(response.input_tokens)
                metadata["reservation_adjustment_tokens"] = adjustment
            payload = json.loads(decrypt_secret(row.payload_encrypted))
            payload["response"] = {
                "content": response.content,
                "turn": None if response.turn is None else response.turn.to_dict(),
                "model": response.model,
                "provider": response.provider,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cache_read_tokens": response.cache_read_tokens,
                "cache_write_tokens": response.cache_write_tokens,
                "reasoning_tokens": response.reasoning_tokens,
                "finish_reason": response.finish_reason,
                "request_id": response.request_id,
                "continuation_id": response.continuation_id,
                "web_citations": response.web_citations,
                "web_tool_activity": response.web_tool_activity,
                "transmitted_input_bytes": response.transmitted_input_bytes,
            }
            row.payload_encrypted = encrypt_secret(json.dumps(payload))
            row.status = "completed"
            try:
                pricing = json.loads(settings.phase8_pricing_json or "{}")
            except json.JSONDecodeError:
                pricing = {}
            rates = pricing.get(f"{row.provider}:{row.model}") or pricing.get(row.provider)
            if (
                isinstance(rates, dict)
                and all(
                    isinstance(rates.get(key), (int, float))
                    for key in ("input_per_million", "output_per_million")
                )
                and response.input_tokens is not None
                and response.output_tokens is not None
            ):
                metadata["estimated_cost"] = round(
                    response.input_tokens * rates["input_per_million"] / 1_000_000
                    + response.output_tokens * rates["output_per_million"] / 1_000_000,
                    8,
                )
                metadata["pricing_version"] = settings.phase8_pricing_version
        else:
            # Exception messages and provider bodies may echo private input or secrets.
            metadata["error_code"] = type(error).__name__
            from app.ai.providers.base import ProviderRequestError

            if isinstance(error, ProviderRequestError):
                metadata["http_status"] = error.status_code
                metadata["error_type"] = error.error_type
                metadata["provider_message"] = error.provider_message
                metadata["provider_request_id"] = error.request_id
                metadata["quota_violations"] = error.quota_violations
                metadata["retry_delay"] = error.retry_delay
            row.status = "failed"
        row.metadata_json = json.dumps(metadata)
        row.completed_at = now()


def provider_error_detail(db, execution_id: str) -> str | None:
    """Return the newest sanitized provider diagnostic for an owned execution."""

    row = db.scalar(
        select(AssistantAttempt)
        .where(
            AssistantAttempt.execution_id == execution_id,
            AssistantAttempt.status == "failed",
        )
        .order_by(AssistantAttempt.created_at.desc())
        .limit(1)
    )
    if row is None:
        return None
    metadata = json.loads(row.metadata_json)
    value = metadata.get("provider_message")
    parts = [value] if isinstance(value, str) and value else []
    for violation in metadata.get("quota_violations") or []:
        if not isinstance(violation, dict):
            continue
        name = violation.get("quotaId") or violation.get("quotaMetric") or "unknown quota"
        details = []
        dimensions = violation.get("quotaDimensions")
        if isinstance(dimensions, dict):
            details.extend(f"{key}={item}" for key, item in dimensions.items())
        if violation.get("quotaValue") is not None:
            details.append(f"limit={violation['quotaValue']}")
        parts.append(f"Quota: {name}" + (f" ({', '.join(details)})" if details else ""))
    if metadata.get("retry_delay"):
        parts.append(f"Retry after: {metadata['retry_delay']}")
    return " ".join(parts)[:2000] or None


def inspect_execution(db, execution):
    attempts = list(db.scalars(
        select(AssistantAttempt)
        .where(AssistantAttempt.execution_id == execution.id)
        .order_by(AssistantAttempt.created_at)
    ))
    attempt_metadata = [json.loads(row.metadata_json) for row in attempts]
    queue_ms = None
    if execution.started_at:
        queue_ms = round(
            (
                execution.started_at.replace(tzinfo=now().tzinfo)
                - execution.created_at.replace(tzinfo=now().tzinfo)
            ).total_seconds()
            * 1000
        )
    return {
        "id": execution.id,
        "status": execution.status,
        "created_at": execution.created_at,
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
        "received_at": execution.received_at,
        "error_code": execution.error_code,
        "queue_ms": queue_ms,
        "retry_count": execution.retry_count,
        "repair_count": execution.repair_count,
        "revision_count": execution.revision_count,
        "reserved_input_tokens": execution.reserved_input_tokens,
        "usage": {
            "input_tokens": sum(
                int(item.get("input_tokens") or item.get("estimated_input_tokens") or 0)
                for item in attempt_metadata
            ),
            "output_tokens": sum(int(item.get("output_tokens") or 0) for item in attempt_metadata),
            "cache_read_tokens": sum(
                int(item.get("cache_read_tokens") or 0) for item in attempt_metadata
            ),
            "reasoning_tokens": sum(
                int(item.get("reasoning_tokens") or 0) for item in attempt_metadata
            ),
            "transmitted_input_bytes": sum(
                int(item.get("transmitted_input_bytes") or 0) for item in attempt_metadata
            ),
            "model_calls": len(attempts),
            "web_tool_steps": sum(
                int(item.get("web_tool_step_count") or 0) for item in attempt_metadata
            ),
        },
        "stages": [
            {
                "id": stage.id,
                "operation": stage.operation,
                "status": stage.status,
                "created_at": stage.created_at,
                "completed_at": stage.completed_at,
                "metadata": json.loads(stage.metadata_json),
            }
            for stage in db.scalars(
                select(AssistantStage).where(AssistantStage.execution_id == execution.id)
            )
        ],
        "attempts": [
            {
                "id": row.id,
                "operation": row.operation,
                "provider": row.provider,
                "status": row.status,
                "created_at": row.created_at,
                "completed_at": row.completed_at,
                "payload_eviction": row.payload_eviction,
                "metadata": {
                    key: value
                    for key, value in json.loads(row.metadata_json).items()
                    if key in SAFE_FIELDS
                },
            }
            for row in attempts
        ],
    }


def cleanup(db, ceiling_bytes=1024**3):
    current = now()
    rows = list(
        db.execute(
            select(AssistantAttempt, AssistantExecution.status)
            .join(AssistantExecution, AssistantExecution.id == AssistantAttempt.execution_id)
            .order_by(AssistantAttempt.created_at)
        )
    )
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
    db.execute(
        delete(AssistantStage)
        .where(AssistantStage.created_at < current - timedelta(days=365))
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(AssistantAttempt)
        .where(AssistantAttempt.created_at < current - timedelta(days=365))
        .execution_options(synchronize_session=False)
    )
    expired_executions = select(AssistantExecution.id).where(
        AssistantExecution.created_at < current - timedelta(days=365)
    )
    db.execute(
        delete(LLMInvocation)
        .where(LLMInvocation.execution_id.in_(expired_executions))
        .execution_options(synchronize_session=False)
    )
    db.execute(
        delete(AssistantExecution)
        .where(AssistantExecution.id.in_(expired_executions))
        .execution_options(synchronize_session=False)
    )
    db.flush()
    return {"retained_payload_bytes": total, "capacity_exceeded": total > ceiling_bytes}


def recovered_response(operation, provider, model, messages):
    """Reuse only byte-identical stage input including current evidence/version references."""
    identifier = execution_id.get()
    if identifier is None:
        return None
    from app.ai.providers.base import LLMProviderResult, ProviderTurn

    with SessionLocal() as db:
        rows = db.scalars(
            select(AssistantAttempt)
            .where(
                AssistantAttempt.execution_id == identifier,
                AssistantAttempt.operation == operation,
                AssistantAttempt.provider == provider,
                AssistantAttempt.model == model,
                AssistantAttempt.status == "completed",
            )
            .order_by(AssistantAttempt.created_at.desc())
        )
        for row in rows:
            if not row.payload_encrypted:
                continue
            payload = json.loads(decrypt_secret(row.payload_encrypted))
            if payload.get("messages") == messages and isinstance(payload.get("response"), str):
                metadata = json.loads(row.metadata_json)
                return LLMProviderResult(
                    content=payload["response"],
                    provider=provider,
                    model=model,
                    **{
                        key: metadata.get(key)
                        for key in (
                            "input_tokens",
                            "output_tokens",
                            "cache_read_tokens",
                            "cache_write_tokens",
                            "reasoning_tokens",
                            "finish_reason",
                        )
                    },
                )
            response = payload.get("response")
            if payload.get("messages") == messages and isinstance(response, dict):
                return LLMProviderResult(
                    content=str(response.get("content") or ""),
                    provider=str(response.get("provider") or provider),
                    model=str(response.get("model") or model),
                    input_tokens=response.get("input_tokens"),
                    output_tokens=response.get("output_tokens"),
                    cache_read_tokens=response.get("cache_read_tokens"),
                    cache_write_tokens=response.get("cache_write_tokens"),
                    reasoning_tokens=response.get("reasoning_tokens"),
                    finish_reason=response.get("finish_reason"),
                    request_id=response.get("request_id"),
                    continuation_id=response.get("continuation_id"),
                    web_citations=response.get("web_citations") or [],
                    web_tool_activity=response.get("web_tool_activity") or [],
                    transmitted_input_bytes=response.get("transmitted_input_bytes"),
                    turn=None
                    if response.get("turn") is None
                    else ProviderTurn.from_dict(response["turn"]),
                )
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


def safe_error_metadata(error):
    """Capture type/code and the innermost code location, never exception text."""
    cause = error
    seen = set()
    while cause.__cause__ is not None and id(cause) not in seen:
        seen.add(id(cause))
        cause = cause.__cause__
    trace = cause.__traceback__
    while trace is not None and trace.tb_next is not None:
        trace = trace.tb_next
    return {
        "error_code": getattr(error, "code", type(error).__name__),
        "exception_type": type(cause).__name__,
        "exception_location": {
            "module": trace.tb_frame.f_globals.get("__name__"),
            "function": trace.tb_frame.f_code.co_name,
            "line": trace.tb_lineno,
        } if trace else None,
    }


def record_tool_failure(name, error, code):
    identifier = begin_stage(f"tool:{name}")
    finish_stage(identifier, status="failed", latency_ms=0, error=error, error_code=code)


def finish_stage(identifier, *, status, latency_ms, validation_count=0, error=None, error_code=None):
    from app.models.assistant_execution import AssistantStage

    if identifier is None:
        return
    with SessionLocal.begin() as db:
        row = db.get(AssistantStage, identifier)
        row.status = status
        row.completed_at = now()
        row.metadata_json = json.dumps(
            {"latency_ms": latency_ms, "validation_failure_count": validation_count,
             **(safe_error_metadata(error) if error is not None else {})}
        )
        if error_code is not None:
            metadata = json.loads(row.metadata_json)
            metadata["error_code"] = error_code
            row.metadata_json = json.dumps(metadata)
