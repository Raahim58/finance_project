"""Offline incident/regression fixtures. No ingestion or paid providers."""
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import settings
from app.core.security import decrypt_secret
from app.db.session import SessionLocal
from app.models.user import User
from app.models.workstation import AssistantMessage
from app.models.assistant_execution import AssistantExecution, AssistantAttempt, now
from app.ai.tool_loop import unwrap_final_text
from app.reasoning.allocation import AllocationProposal, calculate_allocation
from app.reasoning.projection import project, encode
from app.services.assistant_execution import accept, reconcile, owned
from app.services import assistant_diagnostics as diagnostics
from app.schemas.assistant import AssistantMessageCreate


@pytest.fixture
def execution(client, monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    client.post("/auth/signup", json={"email": "revamp@example.com", "password": "password123"})
    with SessionLocal() as db:
        user = db.scalar(select(User))
        row = accept(db, user, AssistantMessageCreate(question="Explain evidence"), "request-1")
        return row.id, user.id


def test_mebl_233_subjects_224_references_have_one_prompt_copy():
    subjects = [{"id": f"subject-{i}", "issuer": "MEBL", "description": "Observed issuer linkage " * 4} for i in range(233)]
    references = [{"evidence_id": f"event-source-{i}", "snippet": f"Unique observed passage {i} " * 4} for i in range(224)]
    context = {"symbol": "MEBL", "subjects": subjects, "evidence": references}
    projected = project({"canonical": context, "deep": [context], "deterministic_fallback": "do not send"})
    raw = encode(projected)
    assert raw.count('"id":"subject-232"') == 1
    assert raw.count('"evidence_id":"event-source-223"') == 1
    assert "do not send" not in raw
    assert projected["counts"]["duplicate_records_removed"] >= 1


@pytest.mark.parametrize("raw", ['```json\n{"answer":"Observed evidence."}\n```', '{"answer":"Observed evidence."}'])
def test_safe_transport_unwraps_without_a_repair_call(raw):
    assert unwrap_final_text(raw) == "Observed evidence."


def calculate(legs, cash="1000", holdings=None, lot=None):
    proposal = AllocationProposal.model_validate({"legs": legs})
    instruments = {"a": {"symbol":"MEBL", "price":"100", "lot_size":lot},
                   "b": {"symbol":"SYS", "price":"50"}}
    return calculate_allocation(proposal, holdings or {}, cash, instruments)


def test_cash_purchase_and_costs_are_gross_and_provisional():
    result = calculate([{"instrument_id":"a","side":"buy","gross_amount":"950"}])
    assert result["accepted"] and result["legs"][0]["quantity"] == "9"
    assert result["proposed_cash"] == "100"
    assert "taxes" in result["cost_note"] and not result["financial_state_mutated"]


def test_explicit_sale_funds_switch_independent_of_leg_order():
    legs = [{"instrument_id":"b","side":"buy","gross_amount":"1000"},
            {"instrument_id":"a","side":"sell","gross_amount":"1000"}]
    result = calculate(legs, cash="0", holdings={"a":Decimal(10)})
    reverse = calculate(list(reversed(legs)), cash="0", holdings={"a":Decimal(10)})
    assert result["accepted"] and result["proposed_cash"] == "0"
    assert result["proposed_weights"] == reverse["proposed_weights"]


@pytest.mark.parametrize("side,cash,holdings,error", [("sell","0",{"a":1},"overselling"), ("buy","0",{"a":1},"unfunded_purchase")])
def test_invalid_funding_rejected(side,cash,holdings,error):
    result = calculate([{"instrument_id":"a","side":side,"gross_amount":"1000"}], cash, holdings)
    assert not result["accepted"] and error in result["errors"]


def test_stored_lot_rule():
    result = calculate([{"instrument_id":"a","side":"buy","gross_amount":"950"}], lot=5)
    assert result["legs"][0]["quantity"] == "5"
    assert result["legs"][0]["quantity_basis"] == "stored_lot_size"


def test_dedup_accept_and_conflicting_reuse(execution):
    identifier, user_id = execution
    with SessionLocal() as db:
        user = db.get(User, user_id)
        second = accept(db, user, AssistantMessageCreate(question="Explain evidence"), "request-1")
        assert second.id == identifier
        assert len(list(db.scalars(select(AssistantMessage)))) == 1
        with pytest.raises(Exception) as exc:
            accept(db, user, AssistantMessageCreate(question="Different content"), "request-1")
        assert exc.value.status_code == 409
        with pytest.raises(Exception) as exc:
            owned(db, "another-owner", identifier)
        assert exc.value.status_code == 404


def test_attempt_survives_final_persistence_failure_and_export_is_redacted(execution):
    identifier, _ = execution
    token = diagnostics.execution_id.set(identifier)
    try:
        attempt = diagnostics.begin_attempt("synthesis", "mock", "mock", [{"role":"user","content":"PRIVATE HOLDINGS"}], 10)
        from app.ai.providers.base import LLMProviderResult
        diagnostics.finish_attempt(attempt, response=LLMProviderResult(content="PRIVATE AMOUNT",model="mock",provider="mock"))
    finally:
        diagnostics.execution_id.reset(token)
    with SessionLocal() as db:
        row = db.get(AssistantAttempt, attempt)
        assert row.status == "completed"
        assert "PRIVATE" not in row.payload_encrypted
        assert "PRIVATE HOLDINGS" in decrypt_secret(row.payload_encrypted)
        export = json.dumps(diagnostics.inspect_execution(db, db.get(AssistantExecution, identifier)), default=str)
        assert "PRIVATE" not in export and "payload_encrypted" not in export
        assert json.loads(row.metadata_json)["input_tokens"] is None


def test_restart_uncertainty_preserves_single_retry_budget(execution):
    identifier, _ = execution
    with SessionLocal.begin() as db:
        row = db.get(AssistantExecution, identifier)
        row.status = "running"
        row.heartbeat_at = now() - timedelta(minutes=10)
        db.add(AssistantAttempt(execution_id=identifier, operation="synthesis",provider="mock",model="mock",status="sent"))
    with SessionLocal() as db:
        assert reconcile(db) == [identifier]
        row = db.get(AssistantExecution, identifier)
        assert row.retry_count == 1
        attempt = db.scalar(select(AssistantAttempt))
        assert attempt.status == "uncertain"
        assert json.loads(attempt.metadata_json)["possible_duplicate_charge"] is True
        row.status = "running"
        db.add(AssistantAttempt(execution_id=identifier,operation="synthesis",provider="mock",model="mock",status="sent"))
        db.commit()
        assert reconcile(db) == []
        assert db.get(AssistantExecution, identifier).error_code == "provider_retry_exhausted"


def test_restart_does_not_replay_uncertain_external_provider_request(execution):
    identifier, _ = execution
    with SessionLocal.begin() as db:
        row = db.get(AssistantExecution, identifier)
        row.status = "running"
        row.heartbeat_at = now() - timedelta(minutes=10)
        db.add(
            AssistantAttempt(
                execution_id=identifier,
                operation="tool_loop_turn_1",
                provider="gemini",
                model="gemini-3-flash-preview",
                status="sent",
            )
        )
    with SessionLocal() as db:
        assert reconcile(db) == []
        row = db.get(AssistantExecution, identifier)
        assert row.status == "failed"
        assert row.error_code == "provider_attempt_uncertain"
        assert db.scalar(select(AssistantAttempt)).status == "uncertain"


def test_payload_retention_sampling_and_eviction(execution):
    identifier, _ = execution
    with SessionLocal.begin() as db:
        execution = db.get(AssistantExecution, identifier)
        execution.status = "failed"
        row = AssistantAttempt(execution_id=identifier,operation="synthesis",provider="mock",model="mock",status="failed",payload_encrypted="x"*200)
        db.add(row)
        db.flush()
        diagnostics.cleanup(db, ceiling_bytes=100)
        assert row.payload_encrypted is None and row.payload_eviction == "capacity"
        row.payload_encrypted = "x"
        row.created_at = now() - timedelta(days=15)
        diagnostics.cleanup(db)
        assert row.payload_eviction == "expired"
    assert diagnostics.sampled(identifier) == diagnostics.sampled(identifier)
    count = sum(diagnostics.sampled(str(i)) for i in range(1000))
    assert 70 <= count <= 130


def test_shariah_aliases_agree_or_remain_unknown():
    from app.services.compliance_service import shariah_eligibility
    assert shariah_eligibility({"shariah_compliant": True}) is True
    assert shariah_eligibility({"shariah_eligible": False}) is False
    assert shariah_eligibility({"shariah_eligible": True, "shariah_compliant": False}) is None
    assert shariah_eligibility({}) is None
    assert shariah_eligibility({"shariah_eligible": "true"}) is None


def test_tool_failure_keeps_safe_type_and_location_in_internal_stage(execution):
    from pydantic import BaseModel
    from app.tools.registry import ToolDefinition, ToolRegistry
    identifier, user_id = execution
    class Input(BaseModel):
        pass
    def failed_handler(*_args):
        raise TypeError("PRIVATE HOLDINGS secret key")
    registry = ToolRegistry()
    registry.register(ToolDefinition("test.failure", "1", "offline", Input,
        "test:read", True, False, 1, "low", failed_handler))
    token = diagnostics.execution_id.set(identifier)
    try:
        with SessionLocal() as db:
            result = registry.invoke("test.failure", db, db.get(User, user_id), {})
            assert result["data"]["error"]["code"] == "handler_unavailable"
            stages = diagnostics.inspect_execution(db, db.get(AssistantExecution, identifier))["stages"]
            failed = next(stage for stage in stages if stage["operation"] == "tool:test.failure")
            assert failed["metadata"]["exception_type"] == "TypeError"
            assert failed["metadata"]["exception_location"]["function"] == "failed_handler"
            assert "PRIVATE" not in json.dumps(failed["metadata"])
    finally:
        diagnostics.execution_id.reset(token)
