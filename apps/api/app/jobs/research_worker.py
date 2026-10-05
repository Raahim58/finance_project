"""Single-concurrency durable research worker. No scheduler and no provider retries."""

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from sqlalchemy import select, text, delete
from app.db.session import SessionLocal, engine
from app.core.security import decrypt_secret, encrypt_secret
from app.domain.research_relevance import canonical, fingerprint
from app.models.user import User
from app.models.workstation import Instrument
from app.models.research_intelligence import ResearchJob, ResearchAttempt
from app.services.research_job_service import TERMINAL
from app.services.research_evidence_service import selected_reports, prepare_report
from app.services.research_intelligence_service import (
    profile_input,
    current_profile,
    digest_input,
    persist_snapshot,
)
from app.services.research_generation_service import (
    generation_request,
    validate_output,
    save_output,
)
from app.services.llm_key_service import get_decrypted_key_for_call
from app.ai.providers.registry import get_provider
from app.ai.providers.base import ProviderCallOptions


async def heartbeat(company_id):
    while True:
        await asyncio.sleep(10)
        with SessionLocal() as db:
            company = db.get(ResearchJob, company_id)
            if not company or company.status != "running":
                return
            company.heartbeat_at = datetime.now(UTC)
            company.lease_until = datetime.now(UTC) + timedelta(seconds=120)
            db.commit()


def recover(db):
    now = datetime.now(UTC)
    for job in db.scalars(
        select(ResearchJob).where(
            ResearchJob.job_type.in_(("company", "company_snapshot")),
            ResearchJob.status == "running",
            ResearchJob.lease_until < now,
        )
    ):
        stages = list(
            db.scalars(
                select(ResearchJob).where(
                    ResearchJob.parent_id == job.parent_id,
                    ResearchJob.instrument_id == job.instrument_id,
                    ResearchJob.job_type.in_(("profile", "digest", "company_brief")),
                )
            )
        )
        uncertain = False
        for stage in stages:
            attempt = db.scalar(select(ResearchAttempt).where(ResearchAttempt.job_id == stage.id))
            if attempt and attempt.status == "request_started" and not attempt.response_encrypted:
                attempt.status = stage.status = "uncertain"
                stage.error_code = "provider_outcome_unknown"
                uncertain = True
        job.status = "uncertain" if uncertain else "queued"
        job.error_code = "provider_outcome_unknown" if uncertain else None
    # Retain encrypted requests/responses 14 days; non-secret usage/status metadata one year.
    for attempt in db.scalars(
        select(ResearchAttempt).where(ResearchAttempt.created_at < now - timedelta(days=14))
    ):
        attempt.request_encrypted = attempt.response_encrypted = None
    for job in db.scalars(
        select(ResearchJob).where(
            ResearchJob.created_at < now - timedelta(days=14), ResearchJob.status.in_(TERMINAL)
        )
    ):
        job.request_encrypted = None
    expired_roots = list(
        db.scalars(
            select(ResearchJob).where(
                ResearchJob.job_type == "batch",
                ResearchJob.created_at < now - timedelta(days=365),
                ResearchJob.status.in_(TERMINAL),
            )
        )
    )
    for root in expired_roots:
        children = list(db.scalars(select(ResearchJob).where(ResearchJob.parent_id == root.id)))
        if any(
            c.status not in TERMINAL or c.created_at >= now - timedelta(days=365) for c in children
        ):
            continue
        ids = [root.id] + [c.id for c in children]
        db.execute(delete(ResearchAttempt).where(ResearchAttempt.job_id.in_(ids)))
        db.execute(delete(ResearchJob).where(ResearchJob.parent_id == root.id))
        db.delete(root)
    db.commit()


async def call_stage(db, company, user, instrument, kind, payload, config):
    key = fingerprint(payload)
    dedup = company.id + ":" + kind + ":" + key
    stage = db.scalar(
        select(ResearchJob).where(ResearchJob.user_id == user.id, ResearchJob.dedup_key == dedup)
    )
    if stage is None:
        stage = ResearchJob(
            user_id=user.id,
            parent_id=company.parent_id,
            instrument_id=instrument.id,
            job_type=kind,
            dedup_key=dedup,
            request_hash=key,
            request_encrypted=encrypt_secret(canonical(payload)),
            max_calls=1,
        )
        db.add(stage)
        db.commit()
    if stage.status in {"failed", "uncertain", "budget_exhausted"}:
        raise RuntimeError(stage.error_code or stage.status)
    if stage.status == "completed":
        return
    messages, schema = generation_request(kind, payload)
    attempt = db.scalar(select(ResearchAttempt).where(ResearchAttempt.job_id == stage.id))
    if attempt and attempt.response_encrypted:
        try:
            output = validate_output(kind, decrypt_secret(attempt.response_encrypted), payload)
        except Exception:
            attempt.status = stage.status = "failed"
            attempt.error_code = stage.error_code = "invalid_model_output"
            db.commit()
            raise RuntimeError("invalid_model_output") from None
    elif attempt and attempt.status != "reserved":
        stage.status = attempt.status = "uncertain"
        stage.error_code = "provider_outcome_unknown"
        db.commit()
        raise RuntimeError("provider_outcome_unknown")
    else:
        if attempt is None:
            root = db.scalar(
                select(ResearchJob).where(ResearchJob.id == company.parent_id).with_for_update()
            )
            if root.reserved_calls >= root.max_calls:
                stage.status = "budget_exhausted"
                stage.error_code = "call_budget_exhausted"
                db.commit()
                raise RuntimeError("call_budget_exhausted")
            root.reserved_calls += 1
            root.status = "running"
            stage.status = "running"
            attempt = ResearchAttempt(
                job_id=stage.id,
                provider=config["provider"],
                model=config["model"],
                status="reserved",
                request_hash=fingerprint(messages),
                request_encrypted=encrypt_secret(canonical(messages)),
            )
            db.add(attempt)
            db.commit()
        # A reserved attempt has not crossed the external boundary. Missing/decryption-failed key is a known failure.
        try:
            api_key, _key_record = get_decrypted_key_for_call(db, user, config["provider"])
            provider = get_provider(config["provider"])
        except Exception:
            attempt.status = stage.status = "failed"
            attempt.error_code = stage.error_code = "provider_key_unavailable"
            db.commit()
            raise RuntimeError("provider_key_unavailable")
        attempt.status = "request_started"
        db.commit()
        started = time.monotonic()
        try:
            result = await provider.chat_with_options(
                api_key,
                messages,
                config["model"],
                options=ProviderCallOptions(
                    response_schema=schema if kind in ("profile", "company_brief") else None,
                    json_mode=True,
                    max_output_tokens=1500 if kind == "profile" else 2500,
                    deadline_seconds=60,
                    thinking_level="minimal"
                    if kind != "company_brief" and config["provider"] == "gemini"
                    and config["model"].startswith("gemini-3-flash")
                    else None,
                ),
            )
        except Exception as exc:
            from app.ai.providers.base import ProviderRequestError

            known_failure = isinstance(exc, ProviderRequestError) and not getattr(
                exc, "retryable", False
            )
            attempt.status = stage.status = "failed" if known_failure else "uncertain"
            attempt.error_code = stage.error_code = (
                "provider_request_failed" if known_failure else "provider_outcome_unknown"
            )
            attempt.latency_ms = int((time.monotonic() - started) * 1000)
            db.commit()
            raise RuntimeError(stage.error_code) from None
        finally:
            api_key = None
        # Persist the response before validation/finalization. A crash can recover locally without a paid replay.
        attempt.response_encrypted = encrypt_secret(result.content)
        attempt.provider_request_id = result.request_id
        attempt.latency_ms = int((time.monotonic() - started) * 1000)
        attempt.usage_json = canonical(
            {
                key: getattr(result, key, None)
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "reasoning_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                )
            }
        )
        attempt.status = "response_received"
        db.commit()
        if kind == "company_brief" and result.finish_reason in ('length','max_tokens','MAX_TOKENS','model_context_window_exceeded','incomplete'):
            attempt.status = stage.status = 'failed'
            attempt.error_code = stage.error_code = 'provider_output_truncated'
            db.commit()
            raise RuntimeError('provider_output_truncated')
        try:
            output = validate_output(kind, result.content, payload)
        except Exception:
            attempt.status = stage.status = "failed"
            attempt.error_code = stage.error_code = "invalid_model_output"
            db.commit()
            raise RuntimeError("invalid_model_output") from None
    save_output(db, user, instrument, kind, payload, output, config["provider"], config["model"])
    stage.status = attempt.status = "completed"
    stage.result_json = canonical(
        {"output_count": len(output.get("relationships", output.get("events", [])))}
    )
    db.commit()


def prepare_company_reports(instrument_id):
    with SessionLocal() as db:
        instrument = db.get(Instrument, instrument_id)
        ids = [r.id for r in selected_reports(db, instrument.symbol)]
        return [prepare_report(db, document_id) for document_id in ids]


async def execute_company(job_id):
    task = asyncio.create_task(heartbeat(job_id))
    try:
        with SessionLocal() as db:
            job = db.get(ResearchJob, job_id)
            user = db.get(User, job.user_id)
            instrument = db.get(Instrument, job.instrument_id)
            config = json.loads(decrypt_secret(job.request_encrypted))
            try:
                if job.job_type == "company_snapshot":
                    from app.services.company_snapshot import build_snapshot, dependency_hash
                    from app.services.company_digest_service import store_snapshot
                    from app.models.research_intelligence import CompanyDigest
                    checkpoint = json.loads(job.result_json or '{}')
                    saved = db.scalar(select(CompanyDigest).where(CompanyDigest.id == checkpoint.get('snapshot_id'),
                        CompanyDigest.user_id == user.id,CompanyDigest.instrument_id == instrument.id)) if checkpoint.get('snapshot_id') else None
                    inputs = saved.input_hash if saved else dependency_hash(db,instrument)
                    if saved is None:
                        saved = db.scalar(select(CompanyDigest).where(CompanyDigest.user_id == user.id,
                            CompanyDigest.instrument_id == instrument.id,CompanyDigest.input_hash == inputs,
                            CompanyDigest.provider == config['provider'],CompanyDigest.model == config['model'],
                            CompanyDigest.prompt_version == 'company-brief.v1'))
                    if saved and saved.brief_json:
                        job.status = "completed"
                    else:
                        payload = json.loads(saved.snapshot_json) if saved else build_snapshot(db,user,instrument)
                        payload['input_hash'] = inputs
                        saved = store_snapshot(db,user,instrument,payload,config)
                        job.result_json = canonical({'snapshot_id':saved.id})
                        db.commit()  # Snapshot survives model failure; previous brief is not erased.
                        await call_stage(db,job,user,instrument,"company_brief",payload,config)
                        job.status = "completed"
                    job.result_json = canonical({'symbol':instrument.symbol,'input_hash':inputs})
                    job.lease_until = None
                    db.commit()
                    finish_batch(db,user,job.parent_id)
                    return
                preparations = await asyncio.to_thread(prepare_company_reports, instrument.id)
                if current_profile(db, user, instrument, **config) is None:
                    await call_stage(
                        db, job, user, instrument, "profile", profile_input(db, instrument), config
                    )
                payload = digest_input(db, user, instrument)
                from app.services.research_generation_service import cached_event_keys

                cached = cached_event_keys(db, user, instrument, payload, **config)
                payload["events"] = [e for e in payload["events"] if e["event_key"] not in cached]
                if payload["events"]:
                    await call_stage(db, job, user, instrument, "digest", payload, config)
                job.status = "completed"
                job.result_json = canonical(
                    {
                        "symbol": instrument.symbol,
                        "reports": preparations,
                        "events": len(payload["events"]),
                        "profile_cached": True,
                    }
                )
            except Exception as exc:
                db.rollback()
                job = db.get(ResearchJob, job_id)
                code = str(exc)
                allowed = {
                    "provider_outcome_unknown",
                    "provider_request_failed",
                    "provider_key_unavailable",
                    "invalid_model_output",
                    "provider_output_truncated",
                    "call_budget_exhausted",
                    "research_input_budget_exceeded",
                }
                job.error_code = code if code in allowed else "evidence_preparation_failed"
                job.status = "uncertain" if code == "provider_outcome_unknown" else "failed"
            job.lease_until = None
            db.commit()
            finish_batch(db, user, job.parent_id)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def finish_batch(db, user, root_id):
    root = db.get(ResearchJob, root_id)
    companies = list(
        db.scalars(
            select(ResearchJob).where(
                ResearchJob.parent_id == root_id, ResearchJob.job_type.in_(("company", "company_snapshot"))
            )
        )
    )
    if not all(c.status in TERMINAL for c in companies):
        return
    root.status = "completed" if all(c.status == "completed" for c in companies) else "failed"
    root.error_code = next((c.error_code for c in companies if c.error_code), None)
    if root.portfolio_id:
        try:
            persist_snapshot(db, user, root.portfolio_id)
        except Exception:
            root.error_code = "snapshot_unavailable"
    db.commit()


async def drain(once=False):
    # Dedicated session-level lock prevents concurrent workers; claims are also SKIP LOCKED.
    with engine.connect() as connection:
        postgres = connection.dialect.name == "postgresql"
        if (
            postgres
            and not connection.execute(text("SELECT pg_try_advisory_lock(903010)")).scalar()
        ):
            raise RuntimeError("A research worker is already active")
        try:
            while True:
                with SessionLocal() as db:
                    recover(db)
                    job = db.scalar(
                        select(ResearchJob)
                        .where(ResearchJob.job_type.in_(("company", "company_snapshot")), ResearchJob.status == "queued")
                        .order_by(ResearchJob.created_at, ResearchJob.id)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    if job:
                        job.status = "running"
                        job.heartbeat_at = datetime.now(UTC)
                        job.lease_until = datetime.now(UTC) + timedelta(seconds=120)
                        job_id = job.id
                        db.commit()
                    else:
                        job_id = None
                    for root in db.scalars(
                        select(ResearchJob).where(
                            ResearchJob.job_type == "batch",
                            ResearchJob.status.in_(("queued", "running")),
                        )
                    ):
                        finish_batch(db, db.get(User, root.user_id), root.id)
                if job_id:
                    await execute_company(job_id)
                elif once:
                    return
                else:
                    await asyncio.sleep(2)
        finally:
            if postgres:
                connection.execute(text("SELECT pg_advisory_unlock(903010)"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--drain", action="store_true")
    args = parser.parse_args()
    asyncio.run(drain(once=args.drain))
