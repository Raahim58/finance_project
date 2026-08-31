"""HTTP-backed LLM providers.

The historical module name is retained to avoid breaking imports. API keys are
passed only in request headers, never included in exceptions or application logs.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.ai.providers.base import LLMProvider, LLMProviderResult
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
            async with httpx.AsyncClient(timeout=min(settings.assistant_timeout_seconds, 15)) as client:
                response = await client.get(self.models_url, headers=self._headers(api_key))
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def _post(self, url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=settings.assistant_timeout_seconds) as client:
                response = await client.post(url, headers=self._headers(api_key), json=payload)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"{self.name} API request timed out") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"{self.name} API request failed") from exc
        if response.status_code >= 400:
            raise RuntimeError(f"{self.name} API request failed with HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"{self.name} API returned invalid JSON") from exc


class OpenAICompatibleProvider(HTTPProvider):
    chat_url: str

    async def chat(self, api_key: str, messages: list[dict[str, str]], model: str | None = None) -> LLMProviderResult:
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
    supports_tool_calling = True
    default_model = "claude-sonnet-4-6"
    models_url = "https://api.anthropic.com/v1/models"
    chat_url = "https://api.anthropic.com/v1/messages"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}

    async def chat(self, api_key: str, messages: list[dict[str, str]], model: str | None = None) -> LLMProviderResult:
        selected_model = model or self.default_model
        system = "\n\n".join(item["content"] for item in messages if item.get("role") == "system")
        turns = [item for item in messages if item.get("role") in {"user", "assistant"}]
        # Grounded portfolio synthesis includes claim-level citations after the prose.
        # A 2K cap can truncate otherwise-valid JSON before the claims array closes.
        payload: dict[str, Any] = {"model": selected_model, "max_tokens": 4096, "messages": turns, "temperature": 0}
        if system:
            payload["system"] = system
        data = await self._post(self.chat_url, api_key, payload)
        blocks = data.get("content") or []
        content = "\n".join(str(block.get("text")) for block in blocks if block.get("type") == "text" and block.get("text"))
        if not content.strip():
            raise RuntimeError("anthropic API response did not contain assistant text")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return LLMProviderResult(
            content=content,
            model=str(data.get("model") or selected_model),
            provider=self.name,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
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
    supports_tool_calling = True
    supports_json_mode = True
    default_model = "gemini-2.5-flash"
    models_url = "https://generativelanguage.googleapis.com/v1beta/models"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    async def chat(self, api_key: str, messages: list[dict[str, str]], model: str | None = None) -> LLMProviderResult:
        selected_model = model or self.default_model
        system = "\n\n".join(item["content"] for item in messages if item.get("role") == "system")
        contents = [
            {"role": "model" if item.get("role") == "assistant" else "user", "parts": [{"text": item["content"]}]}
            for item in messages if item.get("role") in {"user", "assistant"}
        ]
        payload: dict[str, Any] = {"contents": contents, "generationConfig": {"temperature": 0}}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        data = await self._post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent",
            api_key,
            payload,
        )
        try:
            parts = data["candidates"][0]["content"]["parts"]
            content = "\n".join(str(part["text"]) for part in parts if part.get("text"))
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("gemini API response did not contain assistant text") from exc
        if not content.strip():
            raise RuntimeError("gemini API returned an empty assistant response")
        usage = (
            data.get("usageMetadata")
            if isinstance(data.get("usageMetadata"), dict)
            else {}
        )
        return LLMProviderResult(
            content=content,
            model=str(data.get("modelVersion") or selected_model),
            provider=self.name,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )


class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    supports_tool_calling = True
    supports_json_mode = True
    default_model = "openai/gpt-4.1-mini"
    models_url = "https://openrouter.ai/api/v1/models"
    chat_url = "https://openrouter.ai/api/v1/chat/completions"
