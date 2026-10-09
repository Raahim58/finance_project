"""Offline assistant workspace contracts and fixtures."""

import asyncio
import json
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.ai.providers.base import ProviderEvent, ContentBlock, ProviderTurn, LLMProviderResult
from app.db.session import SessionLocal
from app.models.user import User
from app.models.workstation import Conversation, AssistantMessage, Instrument
from app.models.assistant_execution import AssistantExecution, now
from app.models.assistant_workspace import ExecutionEvent, ConversationSummary
from app.schemas.assistant import AssistantMessageCreate, AssistantPageContext
from app.services import (
    assistant_execution,
    assistant_events,
    assistant_memory,
    assistant_diagnostics,
)
from app.services.assistant_policy import selected_policy
from app.core.config import settings
from app.tests.support.assistant import signup, accepted


def test_snapshot_idempotency_and_active_conversation(client):
    headers, user_id, identifier, conversation_id = accepted(client)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        row = db.get(AssistantExecution, identifier)
        policy = json.loads(row.policy_json)
        assert policy["input"] == 48000 and policy["history"] == 24000
        original = db.scalar(
            select(AssistantMessage).where(AssistantMessage.execution_id == identifier)
        )
        assert json.loads(original.context_json)["page"] == "workspace"
        with pytest.raises(Exception) as exc:
            assistant_execution.accept(
                db, user, AssistantMessageCreate(question="Second"), "another", conversation_id
            )
        assert exc.value.status_code == 409
    assert (
        client.post(f"/assistant/runs/{identifier}/cancel", headers=headers).json()["status"]
        == "stopped"
    )
    assert (
        client.post(f"/assistant/runs/{identifier}/cancel", headers=headers).json()["status"]
        == "stopped"
    )
    with SessionLocal() as db:
        assert (
            len(list(db.scalars(select(ExecutionEvent).where(ExecutionEvent.kind == "terminal"))))
            == 1
        )


def test_context_changes_apply_only_to_subsequent_messages(client):
    headers, user_id, identifier, conversation_id = accepted(client)
    with SessionLocal.begin() as db:
        db.get(AssistantExecution, identifier).status = "completed"
        db.add_all(
            [
                Instrument(id="ogdc", symbol="OGDC", name="Oil and Gas"),
                Instrument(id="luck", symbol="LUCK", name="Lucky"),
            ]
        )
    for company in ["ogdc", "luck"]:
        with SessionLocal() as db:
            row = assistant_execution.accept(
                db,
                db.get(User, user_id),
                AssistantMessageCreate(
                    question=company,
                    page_context=AssistantPageContext(page="company", instrument_id=company),
                ),
                str(uuid4()),
                conversation_id,
            )
            row.status = "completed"
            db.commit()
    history = client.get(
        f"/assistant/workspace/conversations/{conversation_id}/messages", headers=headers
    ).json()
    assert [m["context"].get("symbol") for m in history["items"]] == [None, "OGDC", "LUCK"]


def test_replay_encryption_pagination_and_ownership(client):
    headers, user_id, identifier, conversation_id = accepted(client)
    stranger = signup(client, "stranger11@example.com")
    assistant_events.append(identifier, "text_delta", {"text": "First "})
    assistant_events.append(identifier, "text_delta", {"text": "second"})
    with SessionLocal.begin() as db:
        row = db.get(AssistantExecution, identifier)
        row.status = "interrupted"
        row.completed_at = now()
        events = assistant_events.replay(db, identifier, 1)
        assert events[0]["sequence"] == 2 and events[0]["payload"]["text"] == "second"
        encrypted = db.scalar(select(ExecutionEvent).where(ExecutionEvent.sequence == 1))
        assert "First" not in encrypted.payload_encrypted
    for path in [
        f"/assistant/runs/{identifier}/events",
        f"/assistant/workspace/conversations/{conversation_id}/messages",
        f"/assistant/workspace/conversations/{conversation_id}/search",
    ]:
        assert client.get(path, headers=stranger).status_code == 404
    assert client.post(f"/assistant/runs/{identifier}/cancel", headers=stranger).status_code == 404
    assert (
        client.post(
            f"/assistant/workspace/conversations/{conversation_id}/retry-summary", headers=stranger
        ).status_code
        == 404
    )
    page = client.get("/assistant/workspace/conversations?limit=1", headers=headers).json()
    assert page["items"][0]["id"] == conversation_id
    replay = client.get(f"/assistant/runs/{identifier}/events?after=1", headers=headers).text
    assert "First " not in replay and "second" in replay and "interrupted" in replay
    with SessionLocal.begin() as db:
        db.get(AssistantExecution, identifier).completed_at = now() - timedelta(hours=25)
    with SessionLocal.begin() as db:
        assistant_events.prune(db)
    with SessionLocal() as db:
        assert db.scalar(select(ExecutionEvent)) is None
        assert db.scalar(select(AssistantMessage)) is not None


@pytest.mark.asyncio
async def test_compaction_failure_suppression_and_version_boundaries(client, monkeypatch):
    _, user_id, identifier, conversation_id = accepted(client)
    policy = selected_policy() | {"history": 1300, "recent": 1000, "summary": 100, "input": 4000}
    monkeypatch.setattr(assistant_memory, "execution_policy", lambda: policy)
    with SessionLocal.begin() as db:
        for index in range(8):
            db.add(
                AssistantMessage(
                    conversation_id=conversation_id,
                    role="user",
                    content="Earlier requirement " + str(index) + " detail " * 10,
                )
            )
    with SessionLocal() as db:
        _, history_rows = assistant_memory.retained_history(db, conversation_id, identifier)
        from app.reasoning.projection import estimate_tokens

        size = estimate_tokens(["", *[assistant_memory.message_record(r) for r in history_rows]])
        policy["history"] = size - 1
        policy["recent"] = size * 3 // 4

    class Provider:
        calls = 0

        async def chat_with_options(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("offline failure")

    provider = Provider()
    await assistant_memory.prepare(
        identifier, user_id, conversation_id, provider, "fixture", "test"
    )
    await assistant_memory.prepare(
        identifier, user_id, conversation_id, provider, "fixture", "test"
    )
    assert provider.calls == 1
    with SessionLocal.begin() as db:
        db.get(Conversation, conversation_id).summary_failure = None

    async def success(*args, **kwargs):
        assert kwargs["options"].thinking is False
        return LLMProviderResult(
            content="Keep requirements and OGDC context dated.",
            provider="mock",
            model="mock",
            input_tokens=100,
            output_tokens=12,
        )

    provider.chat_with_options = success
    await assistant_memory.prepare(
        identifier, user_id, conversation_id, provider, "fixture", "test"
    )
    with SessionLocal() as db:
        summaries = list(db.scalars(select(ConversationSummary)))
        assert len(summaries) == 1 and summaries[0].covered_through_message_id
        assert len(list(db.scalars(select(AssistantMessage)))) == 9
        assert db.get(Conversation, conversation_id).summary_failure is None
        assert (
            len(json.loads(db.get(AssistantExecution, identifier).accounting_json)["summaries"])
            == 2
        )


@pytest.mark.asyncio
async def test_stream_chunks_batch_and_terminal_partial_survives_pruning(client):
    headers, _, identifier, conversation_id = accepted(client)
    batch = assistant_events.StreamBatch(identifier)
    await batch(ProviderEvent("text_delta", text="Partial text"))
    await asyncio.sleep(0.3)
    with SessionLocal() as db:
        assert len(assistant_events.replay(db, identifier)) == 1
    with SessionLocal() as db:
        assistant_execution.cancel(db, db.get(AssistantExecution, identifier).user_id, identifier)
    batch.close()
    with SessionLocal.begin() as db:
        row = db.get(AssistantExecution, identifier)
        row.completed_at = now() - timedelta(hours=25)
    with SessionLocal.begin() as db:
        assistant_events.prune(db)
    history = client.get(
        f"/assistant/workspace/conversations/{conversation_id}/messages", headers=headers
    ).json()
    assert (
        history["items"][-1]["content"] == "Partial text"
        and history["items"][-1]["outcome"] == "stopped"
    )


@pytest.mark.asyncio
async def test_capacity_wait_remains_durable_then_runs_without_increasing_slots(
    client, monkeypatch
):
    _, _, identifier, _ = accepted(client)
    monkeypatch.setattr(assistant_execution, "_slots", asyncio.Semaphore(0))
    monkeypatch.setattr(settings, "assistant_queue_timeout_seconds", 0.01)
    claimed = []

    async def execute_claimed(value):
        claimed.append(value)

    monkeypatch.setattr(assistant_execution, "_execute_claimed", execute_claimed)
    task = asyncio.create_task(assistant_execution.execute(identifier))
    await asyncio.sleep(0.03)
    with SessionLocal() as db:
        row = db.get(AssistantExecution, identifier)
        assert row.status == "queued" and row.started_at is None
        assert row.error_code is None
    assert not claimed
    assistant_execution._slots.release()
    await task
    assert claimed == [identifier]
    assert assistant_execution._slots._value == 1


@pytest.mark.asyncio
async def test_committed_response_checkpoint_gap_reuses_response_without_model(client):
    from app.ai.tool_loop import _provider_turn

    _, _, identifier, _ = accepted(client)
    token = assistant_diagnostics.execution_id.set(identifier)
    try:
        record = [{"role": "user", "content": '{"messages": "exact serialized input"}'}]
        attempt = assistant_diagnostics.begin_attempt(
            "tool_loop_turn", "zai", "glm-4.7-flash", record, 12
        )
        assistant_diagnostics.finish_attempt(
            attempt,
            response=LLMProviderResult(
                content="Already paid for and complete",
                provider="zai",
                model="glm-4.7-flash",
                input_tokens=12,
                output_tokens=7,
                finish_reason="stop",
                turn=ProviderTurn(
                    "assistant", [ContentBlock("text", text="Already paid for and complete")]
                ),
            ),
            latency_ms=10,
        )

        class Provider:
            name = "zai"
            default_model = "glm-4.7-flash"

            async def tool_chat_with_options(self, *args, **kwargs):
                raise AssertionError("Recovery must not call a model")

        result = await _provider_turn(Provider(), "offline-fixture", None, [], [])
        assert result.content == "Already paid for and complete" and result.output_tokens == 7
    finally:
        assistant_diagnostics.execution_id.reset(token)
