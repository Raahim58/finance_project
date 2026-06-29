import pytest

from app.ai.providers.registry import get_provider, list_provider_names


@pytest.mark.asyncio
async def test_mock_provider_contract():
    provider = get_provider("mock")
    assert provider.name == "mock"
    assert provider.supports_tool_calling is True
    assert await provider.validate_key("mock-test-key") is True

    result = await provider.chat(
        api_key="mock-test-key",
        messages=[{"role": "user", "content": "Hello"}],
    )
    assert result.provider == "mock"
    assert "Hello" in result.content


def test_expected_provider_names_are_registered():
    assert list_provider_names() == ["anthropic", "gemini", "mock", "openai", "openrouter"]
