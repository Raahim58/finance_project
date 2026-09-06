from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


class ProviderRequestError(RuntimeError):
    """Sanitized non-success response metadata from an external LLM provider."""

    def __init__(
        self,
        *,
        provider: str,
        status_code: int,
        error_type: str | None = None,
        provider_message: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        self.error_type = error_type
        self.provider_message = provider_message
        self.request_id = request_id
        detail = f"{provider} API request failed with HTTP {status_code}"
        if error_type:
            detail += f" ({error_type})"
        if provider_message:
            detail += f": {provider_message}"
        if request_id:
            detail += f" [request_id={request_id}]"
        super().__init__(detail)


@dataclass(frozen=True)
class LLMProviderResult:
    content: str
    model: str
    provider: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMProvider(ABC):
    name: str
    supports_tool_calling: bool
    supports_json_mode: bool
    max_context_tokens: int
    default_model: str

    @abstractmethod
    async def validate_key(self, api_key: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def chat(
        self,
        api_key: str,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> LLMProviderResult:
        raise NotImplementedError

    async def stream_chat(
        self,
        api_key: str,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> AsyncIterator[str]:
        result = await self.chat(api_key=api_key, messages=messages, model=model)
        yield result.content
