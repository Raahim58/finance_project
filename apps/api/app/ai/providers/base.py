from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal


BlockType = Literal["text", "tool_call", "tool_result", "image"]


@dataclass(frozen=True)
class ContentBlock:
    """Provider-neutral message block without flattening tool or image turns."""

    type: BlockType
    text: str | None = None
    id: str | None = None
    name: str | None = None
    arguments: dict[str, Any] | None = None
    result: Any = None
    is_error: bool = False
    mime_type: str | None = None
    data: str | None = None
    opaque: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "type": self.type,
                "text": self.text,
                "id": self.id,
                "name": self.name,
                "arguments": self.arguments,
                "result": self.result,
                "is_error": self.is_error,
                "mime_type": self.mime_type,
                "data": self.data,
                "opaque": self.opaque,
            }.items()
            if value not in (None, {}, False)
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ContentBlock":
        return cls(**value)


@dataclass(frozen=True)
class ProviderTurn:
    role: Literal["system", "user", "assistant"]
    content: list[ContentBlock]
    opaque: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "role": self.role,
            "content": [block.to_dict() for block in self.content],
        }
        if self.opaque:
            result["opaque"] = self.opaque
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProviderTurn":
        return cls(
            role=value["role"],
            content=[ContentBlock.from_dict(block) for block in value.get("content", [])],
            opaque=value.get("opaque", {}),
        )


@dataclass(frozen=True)
class ProviderTool:
    name: str
    description: str
    input_schema: dict[str, Any]


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
        quota_violations: list[dict[str, Any]] | None = None,
        retry_delay: str | None = None,
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        self.error_type = error_type
        self.provider_message = provider_message
        self.request_id = request_id
        self.quota_violations = quota_violations or []
        self.retry_delay = retry_delay
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
    turn: ProviderTurn | None = None
    continuation_id: str | None = None
    web_citations: list[dict[str, Any]] = field(default_factory=list)
    web_tool_activity: list[dict[str, Any]] = field(default_factory=list)
    transmitted_input_bytes: int | None = None


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

    async def tool_chat(
        self,
        api_key: str,
        turns: list[ProviderTurn],
        tools: list[ProviderTool],
        model: str | None = None,
    ) -> LLMProviderResult:
        """Compatibility fallback for consumers/providers without native tool transport."""

        messages = []
        for turn in turns:
            text = "\n".join(
                block.text for block in turn.content if block.type == "text" and block.text
            )
            if text:
                messages.append({"role": turn.role, "content": text})
        result = await self.chat(api_key, messages, model)
        if result.turn is not None:
            return result
        return LLMProviderResult(
            **{key: getattr(result, key) for key in result.__dataclass_fields__ if key != "turn"},
            turn=ProviderTurn("assistant", [ContentBlock("text", text=result.content)]),
        )

    async def tool_chat_with_options(
        self,
        api_key: str,
        turns: list[ProviderTurn],
        tools: list[ProviderTool],
        model: str | None = None,
        *,
        options: "ProviderCallOptions",
    ) -> LLMProviderResult:
        import asyncio

        token = call_options.set(options)
        try:
            async with asyncio.timeout(options.deadline_seconds):
                return await self.tool_chat(api_key, turns, tools, model)
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
    deadline_seconds: float = 30
    continuation_id: str | None = None


@dataclass(frozen=True)
class ProviderCapabilities:
    structured_output: bool = False
    schema_in_prompt: bool = True
    usage_breakdown: bool = True


call_options: ContextVar[ProviderCallOptions] = ContextVar(
    "provider_call_options", default=ProviderCallOptions()
)
