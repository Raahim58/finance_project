"""Offline research worker contracts and fixtures."""

import asyncio
import json
from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.core.security import encrypt_secret
from app.models.user import User
from app.models.research_intelligence import ResearchJob, ResearchAttempt, CompanyEventBrief
from app.schemas.research_intelligence import BatchRequest
from app.services.research_intelligence_service import company_intelligence
from app.services.research_job_service import preview_batch, enqueue_batch, job_status
from app.ai.providers.base import LLMProviderResult
from app.jobs import research_worker
from app.tests.support.research import seed
import pytest

pytestmark = pytest.mark.usefixtures("database")


def test_worker_one_turn_calls_cache_and_never_exposes_keys(monkeypatch):
    calls = []

    class Provider:
        async def chat_with_options(self, key, messages, model, *, options):
            assert (
                key == "offline-test-key" and len(messages) == 2 and options.continuation_id is None
            )
            payload = json.loads(
                messages[1]["content"].split("INPUT_JSON\n")[1].split("\nOUTPUT_SCHEMA")[0]
            )
            calls.append(payload)
            if "allowed_factors" in payload:
                result = {"relationships": [], "coverage_gaps": ["No retained reports"]}
            else:
                events = []
                for e in payload["events"]:
                    ref = e["evidence"][0]["id"]
                    events.append(
                        {
                            "event_key": e["event_key"],
                            "relationship_kind": e["relationship_kind"],
                            "status": "explained",
                            "what_happened": {
                                "text": "Quarterly results were announced.",
                                "evidence_ids": [ref],
                                "fact_ids": [],
                            },
                            "why_it_matters": [],
                            "countereffects": [],
                            "unknowns": ["Financial consequences not established."],
                        }
                    )
                result = {"events": events}
            return LLMProviderResult(
                content=json.dumps(result),
                provider="gemini",
                model=model,
                input_tokens=100,
                output_tokens=50,
            )

    monkeypatch.setattr(research_worker, "get_provider", lambda _: Provider())
    with SessionLocal() as db:
        user, _, a, _ = seed(db)
        uid = user.id
        aid = a.id
        root = enqueue_batch(
            db, user, BatchRequest(client_request_id="worker-1", instrument_ids=[aid])
        )
    asyncio.run(research_worker.drain(once=True))
    with SessionLocal() as db:
        user = db.get(User, uid)
        status = job_status(db, user, root["id"])
        assert status["status"] == "completed" and status["reserved_calls"] == 2
        assert status["actual_usage"]["input_tokens"] == 200
        assert "offline-test-key" not in json.dumps(status)
        result = company_intelligence(db, user, "AAA")
        assert result["events"][0]["saved_brief"]["explanation"]["what_happened"]["text"]
        preview = preview_batch(
            db, user, BatchRequest(client_request_id="worker-2", instrument_ids=[aid])
        )
        assert preview["maximum_calls"] == 0
        enqueue_batch(db, user, BatchRequest(client_request_id="worker-2", instrument_ids=[aid]))
    asyncio.run(research_worker.drain(once=True))
    assert len(calls) == 2


def test_worker_uncertain_call_is_not_replayed(monkeypatch):
    calls = []

    class Provider:
        async def chat_with_options(self, *args, **kwargs):
            calls.append(1)
            raise TimeoutError()

    monkeypatch.setattr(research_worker, "get_provider", lambda _: Provider())
    with SessionLocal() as db:
        user, _, a, _ = seed(db)
        enqueue_batch(db, user, BatchRequest(client_request_id="uncertain", instrument_ids=[a.id]))
    asyncio.run(research_worker.drain(once=True))
    asyncio.run(research_worker.drain(once=True))
    assert len(calls) == 1
    with SessionLocal() as db:
        assert db.scalar(select(ResearchAttempt)).status == "uncertain"
        assert db.scalar(select(func.count()).select_from(CompanyEventBrief)) == 0


def test_response_checkpoint_recovers_without_second_provider_call(monkeypatch):
    from types import SimpleNamespace
    from app.services.research_intelligence_service import profile_input
    from app.domain.research_relevance import canonical, fingerprint

    with SessionLocal() as db:
        user, _, instrument, _ = seed(db)
        root = enqueue_batch(
            db, user, BatchRequest(client_request_id="checkpoint", instrument_ids=[instrument.id])
        )
        company = db.scalar(
            select(ResearchJob).where(
                ResearchJob.parent_id == root["id"], ResearchJob.job_type == "company"
            )
        )
        payload = profile_input(db, instrument)
        stage = ResearchJob(
            user_id=user.id,
            parent_id=root["id"],
            instrument_id=instrument.id,
            job_type="profile",
            dedup_key=company.id + ":profile:" + fingerprint(payload),
            request_hash=fingerprint(payload),
            status="running",
            max_calls=1,
        )
        db.add(stage)
        db.flush()
        db.add(
            ResearchAttempt(
                job_id=stage.id,
                provider="gemini",
                model="offline-test-model",
                status="response_received",
                request_hash=fingerprint(payload),
                response_encrypted=encrypt_secret(
                    canonical({"relationships": [], "coverage_gaps": ["No reports"]})
                ),
            )
        )
        db.commit()

        async def should_not_call(*_args, **_kwargs):
            raise AssertionError("Paid replay")

        monkeypatch.setattr(
            research_worker,
            "get_provider",
            lambda _: SimpleNamespace(chat_with_options=should_not_call),
        )
        asyncio.run(
            research_worker.call_stage(
                db,
                company,
                user,
                instrument,
                "profile",
                payload,
                {"provider": "gemini", "model": "offline-test-model"},
            )
        )
        assert db.get(ResearchJob, stage.id).status == "completed"
        assert db.scalar(select(func.count()).select_from(ResearchAttempt)) == 1


def test_reserved_call_recovers_without_reserving_twice(monkeypatch):
    from types import SimpleNamespace
    from app.services.research_intelligence_service import profile_input
    from app.domain.research_relevance import fingerprint

    with SessionLocal() as db:
        user, _, instrument, _ = seed(db)
        root = enqueue_batch(
            db, user, BatchRequest(client_request_id="reserved", instrument_ids=[instrument.id])
        )
        company = db.scalar(
            select(ResearchJob).where(
                ResearchJob.parent_id == root["id"], ResearchJob.job_type == "company"
            )
        )
        payload = profile_input(db, instrument)
        stage = ResearchJob(
            user_id=user.id,
            parent_id=root["id"],
            instrument_id=instrument.id,
            job_type="profile",
            dedup_key=company.id + ":profile:" + fingerprint(payload),
            request_hash=fingerprint(payload),
            status="running",
            max_calls=1,
        )
        db.add(stage)
        db.flush()
        db.add(
            ResearchAttempt(
                job_id=stage.id,
                provider="gemini",
                model="offline-test-model",
                status="reserved",
                request_hash=fingerprint(payload),
            )
        )
        db.get(ResearchJob, root["id"]).reserved_calls = 1
        db.commit()
        calls = []

        async def respond(*args, **kwargs):
            calls.append(args)
            return LLMProviderResult(
                provider="gemini",
                model="offline-test-model",
                content='{"relationships":[],"coverage_gaps":["No reports"]}',
            )

        monkeypatch.setattr(
            research_worker, "get_provider", lambda _: SimpleNamespace(chat_with_options=respond)
        )
        asyncio.run(
            research_worker.call_stage(
                db,
                company,
                user,
                instrument,
                "profile",
                payload,
                {"provider": "gemini", "model": "offline-test-model"},
            )
        )
        assert len(calls) == 1
        assert db.get(ResearchJob, root["id"]).reserved_calls == 1
        assert stage.status == "completed"
