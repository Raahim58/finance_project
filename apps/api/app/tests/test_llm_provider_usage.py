import pytest

from app.ai.providers.http_placeholders import (
    AnthropicProvider,
    GeminiProvider,
    OpenAIProvider,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "response", "expected"),
    [
        (
            OpenAIProvider(),
            {
                "model": "gpt-test",
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 101, "completion_tokens": 29},
            },
            (101, 29),
        ),
        (
            AnthropicProvider(),
            {
                "model": "claude-test",
                "content": [{"type": "text", "text": "answer"}],
                "usage": {"input_tokens": 202, "output_tokens": 41},
            },
            (202, 41),
        ),
        (
            GeminiProvider(),
            {
                "modelVersion": "gemini-test",
                "candidates": [{"content": {"parts": [{"text": "answer"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 303,
                    "candidatesTokenCount": 53,
                },
            },
            (303, 53),
        ),
    ],
)
async def test_provider_usage_is_preserved(provider, response, expected, monkeypatch):
    async def fake_post(*_args, **_kwargs):
        return response

    monkeypatch.setattr(provider, "_post", fake_post)

    result = await provider.chat(
        "secret", [{"role": "user", "content": "question"}], "test-model"
    )

    assert (result.input_tokens, result.output_tokens) == expected
