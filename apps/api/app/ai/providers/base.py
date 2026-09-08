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
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    finish_reason: str | None = None
    request_id: str | None = None


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

    async def chat_with_options(self, api_key, messages, model=None, *, options):
        import asyncio
        token = call_options.set(options)
        try:
            async with asyncio.timeout(options.deadline_seconds):
                return await self.chat(api_key, messages, model)
        finally:
            call_options.reset(token)

    @property
    def capabilities(self):
        return ProviderCapabilities(structured_output=self.name == "gemini")

    async def stream_chat(
        self,
        api_key: str,
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> AsyncIterator[str]:
        result = await self.chat(api_key=api_key, messages=messages, model=model)
        yield result.content


@dataclass(frozen=True)
class ProviderCallOptions:
    response_schema: dict | None = None
    max_output_tokens: int = 4096
    deadline_seconds: float = 120


@dataclass(frozen=True)
class ProviderCapabilities:
    structured_output: bool = False
    schema_in_prompt: bool = True
    usage_breakdown: bool = True


from contextvars import ContextVar
call_options: ContextVar[ProviderCallOptions] = ContextVar("provider_call_options", default=ProviderCallOptions())
