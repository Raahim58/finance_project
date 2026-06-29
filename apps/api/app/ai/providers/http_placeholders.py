from app.ai.providers.base import LLMProvider, LLMProviderResult


class HeaderOnlyProvider(LLMProvider):
    supports_tool_calling = False
    supports_json_mode = False
    max_context_tokens = 16_000

    async def validate_key(self, api_key: str) -> bool:
        return len(api_key.strip()) >= 12

    async def chat(
        self,
        api_key: str,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> LLMProviderResult:
        raise NotImplementedError(
            f"{self.name} network calls are not enabled in Phase 1. "
            "The provider contract is ready for a later adapter implementation."
        )


class AnthropicProvider(HeaderOnlyProvider):
    name = "anthropic"
    supports_tool_calling = True
    default_model = "claude-3-5-sonnet-latest"


class OpenAIProvider(HeaderOnlyProvider):
    name = "openai"
    supports_tool_calling = True
    supports_json_mode = True
    default_model = "gpt-4.1-mini"


class GeminiProvider(HeaderOnlyProvider):
    name = "gemini"
    supports_tool_calling = True
    default_model = "gemini-1.5-pro"


class OpenRouterProvider(HeaderOnlyProvider):
    name = "openrouter"
    supports_tool_calling = True
    supports_json_mode = True
    default_model = "openai/gpt-4.1-mini"
