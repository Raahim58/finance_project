"""Offline assistant request budget contracts and fixtures."""

from app.services.assistant_policy import selected_policy
from app.core.config import settings


def test_trial_selection_is_explicit_and_excludes_reasoning(monkeypatch):
    first = selected_policy()
    monkeypatch.setattr(settings, "assistant_token_trial", "trial2")
    second = selected_policy()
    assert first["history"] == 24000 and second["history"] == 64000
    assert second["cumulative_input"] == first["cumulative_input"] == 180000
    assert first["calls"] == second["calls"] == 6


def test_budget_enforced_at_actual_request_boundary(client, monkeypatch):
    from app.tests.support.assistant import _auth_with_anthropic
    from app.ai.providers.http_placeholders import AnthropicProvider
    from app.services import assistant_policy

    headers, _ = _auth_with_anthropic(client, monkeypatch, email="budget11@example.com")
    provider = AnthropicProvider()
    requests = []

    async def post(url, key, payload):
        requests.append(payload)
        return {
            "id": "budget-call",
            "model": "claude-test",
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"tool{len(requests)}",
                    "name": "market__freshness",
                    "input": {},
                }
            ],
            "usage": {"input_tokens": 40000, "output_tokens": 100},
        }

    monkeypatch.setattr(provider, "_post", post)
    monkeypatch.setattr("app.ai.tool_loop.get_provider", lambda _: provider)
    policy = assistant_policy.selected_policy() | {"cumulative_input": 45000}
    monkeypatch.setattr(assistant_policy, "selected_policy", lambda: policy)
    response = client.post(
        "/assistant/messages",
        headers=headers,
        json={"question": "Inspect evidence", "provider": "anthropic"},
    )
    assert response.status_code == 201
    assert len(requests) == 1
    assert response.json()["synthesis"]["generation"]["error_code"] == "question_budget_exhausted"
    assert requests[0]["max_tokens"] == 8192
    assert requests[0]["thinking"] == {"type": "adaptive"}
