"""Explicit batch preview/enqueue. Preview and polling never generate or ingest."""

import json
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core.security import encrypt_secret
from app.domain.research_relevance import canonical, fingerprint
from app.models.research_intelligence import ResearchJob, ResearchAttempt
from app.models.workstation import Instrument
from app.models.llm_key import LLMApiKey
from app.services.portfolio_service import get_portfolio_or_404, get_portfolio_summary
from app.services.research_intelligence_service import current_profile, company_events, digest_input
from app.services.research_evidence_service import report_coverage

TERMINAL = {"completed", "failed", "uncertain", "skipped", "budget_exhausted"}


def selected_companies(db, user, request):
    if request.portfolio_id:
        portfolio = get_portfolio_or_404(db, user, request.portfolio_id)
        if portfolio.archived_at is not None:
            raise HTTPException(409, "Archived portfolio")
        symbols = [h.symbol for h in get_portfolio_summary(db, user, request.portfolio_id).holdings]
        instruments = list(
            db.scalars(
                select(Instrument).where(Instrument.symbol.in_(symbols)).order_by(Instrument.symbol)
            )
        )
    else:
        instruments = list(
            db.scalars(
                select(Instrument)
                .where(Instrument.id.in_(request.instrument_ids))
                .order_by(Instrument.symbol)
            )
        )
        if len(instruments) != len(request.instrument_ids):
            raise HTTPException(404, "Company not found")
    if len(instruments) > request.max_companies:
        raise HTTPException(
            422,
            "Select at most eight companies; choose explicit company IDs for a larger portfolio",
        )
    return instruments


def generation_config(db, user):
    preferred = user.preferences.default_llm_provider if user.preferences else None
    keys = list(
        db.scalars(
            select(LLMApiKey)
            .where(LLMApiKey.user_id == user.id, LLMApiKey.is_active.is_(True))
            .order_by(LLMApiKey.created_at.desc())
        )
    )
    key = next((k for k in keys if k.provider == preferred), keys[0] if keys else None)
    if key is None:
        return None
    from app.ai.providers.registry import get_provider

    if key.provider == "mock":
        raise HTTPException(422, "Saved research requires a real provider key")
    return {
        "provider": key.provider,
        "model": key.default_model or get_provider(key.provider).default_model,
    }


def preview_batch(db, user, request):
    companies = []
    configuration = generation_config(db, user) or {}
    for instrument in selected_companies(db, user, request):
        coverage = report_coverage(db, instrument.symbol)
        prep = sum(not r["indexed"] for r in coverage)
        profile = current_profile(db, user, instrument, **configuration)
        events = company_events(db, user, instrument)
        from app.services.research_generation_service import cached_event_keys

        cached = bool(events) and len(
            cached_event_keys(
                db, user, instrument, digest_input(db, user, instrument, events), **configuration
            )
        ) == len(events)
        # Report preparation may reveal indirect matches; reserve one digest call if it could.
        calls = int(profile is None) + int(
            (bool(events) or prep > 0 or profile is None) and not cached
        )
        companies.append(
            {
                "instrument_id": instrument.id,
                "symbol": instrument.symbol,
                "reports_to_index": prep,
                "profile_cached": profile is not None,
                "digest_cached": cached,
                "selected_events": len(events),
                "max_calls": calls,
            }
        )
    calls = sum(c["max_calls"] for c in companies)
    return {
        "companies": companies,
        "maximum_calls": calls,
        "budget_calls": request.max_calls,
        "within_budget": calls <= request.max_calls,
        "estimated_input_tokens_upper_bound": sum(
            8000 * int(not c["profile_cached"]) + 10000 * int(not c["digest_cached"])
            for c in companies
        ),
        "estimated_output_tokens_upper_bound": sum(
            1500 * int(not c["profile_cached"]) + 2500 * int(not c["digest_cached"])
            for c in companies
        ),
        "provider_config": generation_config(db, user),
        "mode": "manual",
        "estimates_are_not_billed_usage": True,
    }


def enqueue_batch(db, user, request):
    request_hash = fingerprint(request.model_dump(mode="json"))
    existing = db.scalar(
        select(ResearchJob).where(
            ResearchJob.user_id == user.id, ResearchJob.dedup_key == request.client_request_id
        )
    )
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(409, "Request ID already used with different inputs")
        return job_status(db, user, existing.id)
    preview = preview_batch(db, user, request)
    if not preview["within_budget"]:
        raise HTTPException(422, "Batch exceeds the selected call budget")
    if preview["maximum_calls"] and not preview["provider_config"]:
        raise HTTPException(422, "Save an active provider key first")
    configuration = preview["provider_config"] or {}
    root = ResearchJob(
        user_id=user.id,
        portfolio_id=request.portfolio_id,
        job_type="batch",
        dedup_key=request.client_request_id,
        request_hash=request_hash,
        request_encrypted=encrypt_secret(
            canonical({**request.model_dump(mode="json"), **configuration})
        ),
        status="queued",
        max_calls=request.max_calls,
        result_json=canonical(preview),
    )
    db.add(root)
    db.flush()
    for company in preview["companies"]:
        db.add(
            ResearchJob(
                user_id=user.id,
                parent_id=root.id,
                portfolio_id=request.portfolio_id,
                instrument_id=company["instrument_id"],
                job_type="company",
                dedup_key=root.id + ":" + company["instrument_id"],
                request_hash=request_hash,
                request_encrypted=encrypt_secret(canonical(configuration)),
                max_calls=2,
                result_json=canonical({"symbol": company["symbol"]}),
            )
        )
    if not preview["companies"]:
        root.status = "completed"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(ResearchJob).where(
                ResearchJob.user_id == user.id, ResearchJob.dedup_key == request.client_request_id
            )
        )
        if existing is None or existing.request_hash != request_hash:
            raise HTTPException(409, "Concurrent request conflict")
        return job_status(db, user, existing.id)
    return job_status(db, user, root.id)


def job_status(db, user, job_id):
    root = db.scalar(
        select(ResearchJob).where(ResearchJob.id == job_id, ResearchJob.user_id == user.id)
    )
    if root is None:
        raise HTTPException(404, "Research job not found")
    children = list(
        db.scalars(
            select(ResearchJob)
            .where(ResearchJob.parent_id == root.id)
            .order_by(ResearchJob.created_at, ResearchJob.id)
        )
    )
    ids = [root.id] + [c.id for c in children]
    attempts = list(db.scalars(select(ResearchAttempt).where(ResearchAttempt.job_id.in_(ids))))
    usage = {
        key: sum(json.loads(a.usage_json).get(key) or 0 for a in attempts)
        for key in (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
        )
    }

    def public(row):
        return {
            "id": row.id,
            "job_type": row.job_type,
            "status": row.status,
            "instrument_id": row.instrument_id,
            "error_code": row.error_code,
            "result": json.loads(row.result_json),
        }

    return {
        **public(root),
        "companies": [public(c) for c in children if c.job_type == "company"],
        "stages": [public(c) for c in children if c.job_type != "company"],
        "reserved_calls": root.reserved_calls,
        "maximum_calls": root.max_calls,
        "actual_usage": usage,
        "usage_complete": all(
            json.loads(a.usage_json).get("input_tokens") is not None for a in attempts
        ),
    }
