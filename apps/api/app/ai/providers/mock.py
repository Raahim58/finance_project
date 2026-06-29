from app.ai.providers.base import LLMProvider, LLMProviderResult


class MockProvider(LLMProvider):
    name = "mock"
    supports_tool_calling = True
    supports_json_mode = True
    max_context_tokens = 8_000
    default_model = "mock-psx-reasoner"

    async def validate_key(self, api_key: str) -> bool:
        return api_key.startswith("mock-") or api_key == "test-key"

    async def chat(
        self,
        api_key: str,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> LLMProviderResult:
        prompt = messages[-1]["content"] if messages else ""
        return LLMProviderResult(
            content=(
                "Mock provider response. No live market or document facts were retrieved. "
                f"User message: {prompt}"
            ),
            model=model or self.default_model,
            provider=self.name,
        )
