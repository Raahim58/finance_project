"""HTTP-backed LLM providers.

The historical module name is retained to avoid breaking imports. API keys are
passed only in request headers, never included in exceptions or application logs.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import httpx

from app.ai.providers.base import (
    ContentBlock,
    LLMProvider,
    LLMProviderResult,
    ProviderRequestError,
    ProviderTool,
    ProviderTurn,
    call_options,
)
from app.core.config import settings


class HTTPProvider(LLMProvider):
    supports_tool_calling = False
    supports_json_mode = False
    max_context_tokens = 16_000
    models_url: str

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async def validate_key(self, api_key: str) -> bool:
        if len(api_key.strip()) < 12:
            return False
        try:
            async with httpx.AsyncClient(
                timeout=min(settings.assistant_timeout_seconds, 15)
            ) as client:
                response = await client.get(self.models_url, headers=self._headers(api_key))
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def _post(self, url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=call_options.get().deadline_seconds) as client:
                response = await client.post(url, headers=self._headers(api_key), json=payload)
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"{self.name} API request timed out") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"{self.name} API request failed") from exc
        if response.status_code >= 400:
            error_type = None
            provider_message = None
            quota_violations: list[dict[str, Any]] = []
            retry_delay = None
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = None
            if isinstance(error_payload, dict):
                error = error_payload.get("error")
                if isinstance(error, dict):
                    if isinstance(error.get("type"), str):
                        error_type = error["type"][:120]
                    elif isinstance(error.get("status"), str):
                        error_type = error["status"][:120]
                    provider_message = _safe_provider_message(error.get("message"), api_key)
                    quota_violations, retry_delay = _safe_google_error_details(
                        error.get("details"), api_key
                    )
                else:
                    if isinstance(error_payload.get("type"), str):
                        error_type = error_payload["type"][:120]
                    provider_message = _safe_provider_message(
                        error_payload.get("message"), api_key
                    )
            request_id = response.headers.get("request-id") or response.headers.get("x-request-id")
            raise ProviderRequestError(
                provider=self.name,
                status_code=response.status_code,
                error_type=error_type,
                provider_message=provider_message,
                request_id=None if request_id is None else request_id[:255],
                quota_violations=quota_violations,
                retry_delay=retry_delay,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"{self.name} API returned invalid JSON") from exc


def _safe_provider_message(value: Any, api_key: str) -> str | None:
    """Retain a useful provider diagnostic without retaining credentials or bodies."""

    if not isinstance(value, str) or not value.strip():
        return None
    message = value.replace(api_key, "[REDACTED]") if api_key else value
    message = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", message)
    message = re.sub(
        r"(?i)((?:x-goog-)?api[_ -]?key|authorization)(\s*[:=]\s*)[^\s,;]+",
        r"\1\2[REDACTED]",
        message,
    )
    return " ".join(message.split())[:1000]


def _safe_google_error_details(
    details: Any, api_key: str
) -> tuple[list[dict[str, Any]], str | None]:
    """Extract non-secret quota and retry metadata from Google RPC errors."""

    if not isinstance(details, list):
        return [], None
    violations: list[dict[str, Any]] = []
    retry_delay = None
    for detail in details:
        if not isinstance(detail, dict):
            continue
        detail_type = str(detail.get("@type") or "")
        if detail_type.endswith("google.rpc.QuotaFailure"):
            for violation in detail.get("violations") or []:
                if not isinstance(violation, dict):
                    continue
                safe: dict[str, Any] = {}
                for key in (
                    "quotaMetric",
                    "quotaId",
                    "quotaValue",
                    "futureQuotaValue",
                    "description",
                ):
                    value = violation.get(key)
                    if isinstance(value, (str, int, float)):
                        safe[key] = _safe_provider_message(str(value), api_key)
                dimensions = violation.get("quotaDimensions")
                if isinstance(dimensions, dict):
                    safe["quotaDimensions"] = {
                        str(key)[:80]: _safe_provider_message(str(value), api_key)
                        for key, value in list(dimensions.items())[:20]
                    }
                if safe:
                    violations.append(safe)
        elif detail_type.endswith("google.rpc.RetryInfo"):
            value = detail.get("retryDelay")
            if isinstance(value, str):
                retry_delay = value[:80]
    return violations[:20], retry_delay


class OpenAICompatibleProvider(HTTPProvider):
    chat_url: str

    async def chat(
        self, api_key: str, messages: list[dict[str, str]], model: str | None = None
    ) -> LLMProviderResult:
        selected_model = model or self.default_model
        data = await self._post(
            self.chat_url,
            api_key,
            {"model": selected_model, "messages": messages, "temperature": 0},
        )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"{self.name} API response did not contain assistant text") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"{self.name} API returned an empty assistant response")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return LLMProviderResult(
            content=content,
            model=str(data.get("model") or selected_model),
            provider=self.name,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )


class AnthropicProvider(HTTPProvider):
    name = "anthropic"
    max_context_tokens = 200_000
    supports_tool_calling = True
    default_model = "claude-sonnet-4-6"
    models_url = "https://api.anthropic.com/v1/models"
    chat_url = "https://api.anthropic.com/v1/messages"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    async def chat(
        self, api_key: str, messages: list[dict[str, str]], model: str | None = None
    ) -> LLMProviderResult:
        selected_model = model or self.default_model
        system = "\n\n".join(item["content"] for item in messages if item.get("role") == "system")
        turns = [item for item in messages if item.get("role") in {"user", "assistant"}]
        # Grounded portfolio synthesis includes claim-level citations after the prose.
        # A 2K cap can truncate otherwise-valid JSON before the claims array closes.
        payload: dict[str, Any] = {
            "model": selected_model,
            "max_tokens": call_options.get().max_output_tokens,
            "messages": turns,
        }
        if system:
            payload["system"] = system
        data = await self._post(self.chat_url, api_key, payload)
        blocks = data.get("content") or []
        content = "\n".join(
            str(block.get("text"))
            for block in blocks
            if block.get("type") == "text" and block.get("text")
        )
        if not content.strip():
            raise RuntimeError("anthropic API response did not contain assistant text")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return LLMProviderResult(
            content=content,
            model=str(data.get("model") or selected_model),
            provider=self.name,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cache_read_tokens=usage.get("cache_read_input_tokens"),
            cache_write_tokens=usage.get("cache_creation_input_tokens"),
            finish_reason=data.get("stop_reason"),
            request_id=data.get("id"),
        )

    @staticmethod
    def _content_block(block: ContentBlock) -> dict[str, Any]:
        if block.type == "text":
            return {"type": "text", "text": block.text or ""}
        if block.type == "tool_call":
            if block.opaque.get("provider_block"):
                return block.opaque["provider_block"]
            return {
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.arguments or {},
            }
        if block.type == "tool_result":
            return {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json_text(block.result),
                "is_error": block.is_error,
            }
        if block.type == "image":
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": block.mime_type,
                    "data": block.data,
                },
            }
        raise ValueError("unsupported_content_block")

    async def tool_chat(
        self,
        api_key: str,
        turns: list[ProviderTurn],
        tools: list[ProviderTool],
        model: str | None = None,
    ) -> LLMProviderResult:
        selected_model = model or self.default_model
        system = "\n\n".join(
            block.text or ""
            for turn in turns
            if turn.role == "system"
            for block in turn.content
            if block.type == "text"
        )
        messages = [
            {
                "role": turn.role,
                "content": [self._content_block(block) for block in turn.content],
            }
            for turn in turns
            if turn.role in {"user", "assistant"}
        ]
        payload: dict[str, Any] = {
            "model": selected_model,
            "max_tokens": call_options.get().max_output_tokens,
            "messages": messages,
            "tools": [
                {
                    "name": wire_tool_name(tool.name),
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in tools
            ],
        }
        if system:
            payload["system"] = system
        data = await self._post(self.chat_url, api_key, payload)
        blocks = []
        names = {wire_tool_name(tool.name): tool.name for tool in tools}
        for item in data.get("content") or []:
            if item.get("type") == "text":
                blocks.append(ContentBlock("text", text=str(item.get("text") or "")))
            elif item.get("type") == "tool_use":
                blocks.append(
                    ContentBlock(
                        "tool_call",
                        id=str(item.get("id") or ""),
                        name=names.get(str(item.get("name")), str(item.get("name"))),
                        arguments=item.get("input") if isinstance(item.get("input"), dict) else {},
                        opaque={"provider_block": item},
                    )
                )
        text = "\n".join(block.text or "" for block in blocks if block.type == "text")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return LLMProviderResult(
            content=text,
            model=str(data.get("model") or selected_model),
            provider=self.name,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cache_read_tokens=usage.get("cache_read_input_tokens"),
            cache_write_tokens=usage.get("cache_creation_input_tokens"),
            finish_reason=data.get("stop_reason"),
            request_id=data.get("id"),
            turn=ProviderTurn("assistant", blocks, {"id": data.get("id")}),
        )


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    supports_tool_calling = True
    supports_json_mode = True
    default_model = "gpt-4.1-mini"
    models_url = "https://api.openai.com/v1/models"
    chat_url = "https://api.openai.com/v1/chat/completions"


class GeminiProvider(HTTPProvider):
    name = "gemini"
    max_context_tokens = 1_000_000
    supports_tool_calling = True
    supports_json_mode = True
    default_model = "gemini-2.5-flash"
    models_url = "https://generativelanguage.googleapis.com/v1beta/models"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    async def chat(
        self, api_key: str, messages: list[dict[str, str]], model: str | None = None
    ) -> LLMProviderResult:
        selected_model = model or self.default_model
        system = "\n\n".join(item["content"] for item in messages if item.get("role") == "system")
        contents = [
            {
                "role": "model" if item.get("role") == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in messages
            if item.get("role") in {"user", "assistant"}
        ]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": call_options.get().max_output_tokens,
            },
        }
        if call_options.get().response_schema:
            payload["generationConfig"].update(
                responseMimeType="application/json",
                responseJsonSchema=call_options.get().response_schema,
            )
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        data = await self._post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent",
            api_key,
            payload,
        )
        try:
            parts = data["candidates"][0]["content"]["parts"]
            content = "\n".join(
                str(part["text"]) for part in parts if part.get("text") and not part.get("thought")
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("gemini API response did not contain assistant text") from exc
        if not content.strip():
            raise RuntimeError("gemini API returned an empty assistant response")
        usage = data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
        return LLMProviderResult(
            content=content,
            model=str(data.get("modelVersion") or selected_model),
            provider=self.name,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            cache_read_tokens=usage.get("cachedContentTokenCount"),
            reasoning_tokens=usage.get("thoughtsTokenCount"),
            finish_reason=(data.get("candidates") or [{}])[0].get("finishReason"),
            request_id=data.get("responseId"),
        )

    @staticmethod
    def _supports_combined_web_tools(model: str) -> bool:
        return model.startswith("gemini-3")

    @staticmethod
    def _initial_interaction_input(turns: list[ProviderTurn]) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for turn in turns:
            if turn.role == "system":
                continue
            content = []
            for block in turn.content:
                if block.type == "text":
                    content.append({"type": "text", "text": block.text or ""})
                elif block.type == "image":
                    content.append(
                        {"type": "image", "mime_type": block.mime_type, "data": block.data}
                    )
            if content:
                steps.append(
                    {
                        "type": "model_output" if turn.role == "assistant" else "user_input",
                        "content": content,
                    }
                )
        return steps

    @staticmethod
    def _continuation_input(turns: list[ProviderTurn]) -> list[dict[str, Any]]:
        if not turns or turns[-1].role != "user":
            raise ValueError("gemini_continuation_requires_tool_results")
        results: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for block in turns[-1].content:
            if block.type == "tool_result":
                current = {
                    "type": "function_result",
                    "name": wire_tool_name(block.name or ""),
                    "call_id": block.id,
                    "result": [{"type": "text", "text": json_text(block.result)}],
                }
                results.append(current)
            elif block.type == "image" and current is not None:
                current["result"].append(
                    {"type": "image", "mime_type": block.mime_type, "data": block.data}
                )
        if not results:
            raise ValueError("gemini_continuation_requires_tool_results")
        return results

    def interaction_payload(
        self,
        turns: list[ProviderTurn],
        tools: list[ProviderTool],
        model: str | None = None,
        *,
        options=None,
    ) -> dict[str, Any]:
        selected_model = model or self.default_model
        options = options or call_options.get()
        system = "\n\n".join(
            block.text or ""
            for turn in turns
            if turn.role == "system"
            for block in turn.content
            if block.type == "text"
        )
        payload: dict[str, Any] = {
            "model": selected_model,
            "store": True,
            "input": self._continuation_input(turns)
            if options.continuation_id
            else self._initial_interaction_input(turns),
            "tools": [
                {
                    "type": "function",
                    "name": wire_tool_name(tool.name),
                    "description": tool.description,
                    "parameters": tool.input_schema,
                }
                for tool in tools
            ],
            "generation_config": {
                "temperature": 0,
                "max_output_tokens": options.max_output_tokens,
            },
        }
        if self._supports_combined_web_tools(selected_model):
            payload["tools"].extend(
                [{"type": "google_search"}, {"type": "url_context"}]
            )
        if options.continuation_id:
            payload["previous_interaction_id"] = options.continuation_id
        if system:
            payload["system_instruction"] = system
        return payload

    async def tool_chat(
        self,
        api_key: str,
        turns: list[ProviderTurn],
        tools: list[ProviderTool],
        model: str | None = None,
    ) -> LLMProviderResult:
        selected_model = model or self.default_model
        payload = self.interaction_payload(turns, tools, selected_model)
        data = await self._post(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            api_key,
            payload,
        )
        names = {wire_tool_name(tool.name): tool.name for tool in tools}
        blocks: list[ContentBlock] = []
        web_citations: list[dict[str, Any]] = []
        web_activity: list[dict[str, Any]] = []
        for index, step in enumerate(data.get("steps") or []):
            step_type = step.get("type")
            if step_type == "function_call":
                blocks.append(
                    ContentBlock(
                        "tool_call",
                        id=str(step.get("id") or f"gemini-call-{index + 1}"),
                        name=names.get(str(step.get("name")), str(step.get("name"))),
                        arguments=step.get("arguments")
                        if isinstance(step.get("arguments"), dict)
                        else {},
                        opaque={"provider_step": step},
                    )
                )
            elif step_type == "model_output":
                for item in step.get("content") or []:
                    if item.get("type") == "text":
                        annotations = item.get("annotations") or []
                        blocks.append(
                            ContentBlock(
                                "text",
                                text=str(item.get("text") or ""),
                                opaque={"annotations": annotations},
                            )
                        )
                        for annotation in annotations:
                            if (
                                annotation.get("type") == "url_citation"
                                and annotation.get("url")
                            ):
                                web_citations.append(
                                    {
                                        "id": "web-"
                                        + hashlib.sha256(
                                            (
                                                str(annotation["url"])
                                                + ":"
                                                + str(annotation.get("start_index"))
                                                + ":"
                                                + str(annotation.get("end_index"))
                                            ).encode()
                                        ).hexdigest()[:24],
                                        "source_name": "Gemini web grounding",
                                        "title": annotation.get("title") or annotation["url"],
                                        "source_url": annotation["url"],
                                        "start_index": annotation.get("start_index"),
                                        "end_index": annotation.get("end_index"),
                                        "source_type": "web",
                                    }
                                )
                    elif item.get("type") == "image":
                        blocks.append(
                            ContentBlock(
                                "image",
                                mime_type=item.get("mime_type"),
                                data=item.get("data"),
                            )
                        )
            elif step_type in {
                "google_search_call",
                "google_search_result",
                "url_context_call",
                "url_context_result",
            }:
                web_activity.append(
                    {
                        key: step.get(key)
                        for key in ("type", "id", "call_id", "status", "arguments")
                        if step.get(key) is not None
                    }
                )
        text = "\n".join(block.text or "" for block in blocks if block.type == "text")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        status = str(data.get("status") or "completed")
        return LLMProviderResult(
            content=text,
            model=str(data.get("model") or selected_model),
            provider=self.name,
            input_tokens=usage.get("total_input_tokens"),
            output_tokens=usage.get("total_output_tokens"),
            cache_read_tokens=usage.get("total_cached_tokens"),
            reasoning_tokens=usage.get("total_thought_tokens"),
            finish_reason=status,
            request_id=data.get("id"),
            turn=ProviderTurn("assistant", blocks, {"interaction_id": data.get("id")}),
            continuation_id=data.get("id"),
            web_citations=web_citations,
            web_tool_activity=web_activity,
            transmitted_input_bytes=len(json_text(payload).encode()),
        )


class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    supports_tool_calling = True
    supports_json_mode = True
    default_model = "openai/gpt-4.1-mini"
    models_url = "https://openrouter.ai/api/v1/models"
    chat_url = "https://openrouter.ai/api/v1/chat/completions"


def wire_tool_name(name: str) -> str:
    """Provider-safe reversible spelling for dotted registry names."""

    return name.replace("__", "____").replace(".", "__")


def json_text(value: Any) -> str:
    import json

    return json.dumps(value, default=str, separators=(",", ":"), ensure_ascii=False)
