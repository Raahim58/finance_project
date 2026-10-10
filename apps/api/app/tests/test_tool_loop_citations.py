"""Offline tool loop citations contracts and fixtures."""

import pytest

import json
from app.ai.providers.http_placeholders import AnthropicProvider
from app.ai.tool_loop import ToolExecution, resolve_citations, unwrap_final_text
from app.core.security import decrypt_secret
from app.db.session import SessionLocal
from app.models.assistant_execution import AssistantExecution
from app.models.workstation import AssistantMessage
from app.tools.registry import tool_result
from app.tests.support.assistant import _auth_with_anthropic


@pytest.mark.parametrize("raw", [
    '{"answer":"Readable response.","claims":[]}',
    '```json\n{"answer":"Readable response."}\n```',
    '{"answer":"Readable response."}',
])
def test_transport_unwrap_keeps_readable_text_without_semantic_label(raw):
    assert unwrap_final_text(raw) == "Readable response."


def test_false_sentence_citation_resolves_as_reference_not_proof():
    checkpoint = {
        "evidence": {
            "E7": {
                "identity": "stored",
                "source": {
                    "id": "citation-7",
                    "title": "Annual report",
                    "source_url": "https://example.test/report",
                    "page_number": 7,
                },
            }
        }
    }

    answer, sources, outcome = resolve_citations("MEBL is made of cheese [[E7]].", checkpoint)

    assert "https://example.test/report" in answer
    assert sources[0]["id"] == "citation-7"
    assert outcome["status"] == "resolved"
    assert outcome["semantic_verification"] == "not_performed"


def test_timestamp_citation_survives_final_delivery_and_checkpoint(client, monkeypatch):
    from datetime import UTC, datetime

    headers, user_id = _auth_with_anthropic(client, monkeypatch, email="timestamp-loop@example.com")
    provider = AnthropicProvider()
    responses = [
        {
            "model": "claude-test",
            "stop_reason": "tool_use",
            "content": [
                {"type": "tool_use", "id": "events-1", "name": "research__events", "input": {}}
            ],
            "usage": {},
        },
        {
            "model": "claude-test",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Stored event [[E1]]."}],
            "usage": {},
        },
    ]

    async def fake_post(*_args):
        return responses.pop(0)

    async def fake_tool(_user_id, call):
        return ToolExecution(
            call,
            tool_result(
                "ok",
                {"events": [{"id": "event-1"}]},
                sources=[
                    {
                        "source_name": "Stored issuer event",
                        "published_at": datetime(2026, 9, 14, tzinfo=UTC),
                    }
                ],
            ),
            1,
        )

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _name: provider)
    monkeypatch.setattr("app.ai.tool_loop._execute_tool", fake_tool)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Read the stored event", "provider": "anthropic"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_citations"][0]["published_at"] == "2026-09-14T00:00:00+00:00"
    assert body["synthesis"]["token_usage"]["model_calls"] == 2
    with SessionLocal() as db:
        saved = db.get(AssistantMessage, body["message_id"])
        assert (
            json.loads(saved.evidence_json)["sources"][0]["published_at"]
            == "2026-09-14T00:00:00+00:00"
        )
        execution = db.get(AssistantExecution, body["synthesis"]["execution_id"])
        checkpoint = json.loads(decrypt_secret(execution.transcript_encrypted))
        assert checkpoint["evidence"]["E1"]["source"]["published_at"] == "2026-09-14T00:00:00+00:00"
