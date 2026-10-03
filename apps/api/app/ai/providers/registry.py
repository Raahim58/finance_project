from app.ai.providers.base import LLMProvider
from app.ai.providers.http_placeholders import (
    AnthropicProvider,
    GeminiProvider,
    OpenAIProvider,
    OpenRouterProvider,
)
from app.ai.providers.mock import MockProvider
from app.ai.providers.zai import ZaiProvider

_PROVIDERS: dict[str, LLMProvider] = {
    provider.name: provider
    for provider in [
        MockProvider(),
        ZaiProvider(),
        AnthropicProvider(),
        OpenAIProvider(),
        GeminiProvider(),
        OpenRouterProvider(),
    ]
}


def get_provider(name: str) -> LLMProvider:
    normalized = name.lower()
    if normalized not in _PROVIDERS:
        raise KeyError(f"Unsupported LLM provider: {name}")
    return _PROVIDERS[normalized]


def list_provider_names() -> list[str]:
    return sorted(_PROVIDERS.keys())
