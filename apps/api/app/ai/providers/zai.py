"""Direct Z.ai transport; one in-flight request per credential across processes."""

import asyncio
import hashlib
import json
import weakref
from contextlib import asynccontextmanager

from sqlalchemy import text

from app.ai.providers.base import ContentBlock, LLMProviderResult, ProviderTurn, call_options
from app.ai.providers.http_placeholders import HTTPProvider, wire_tool_name
from app.db.session import engine

_locks = weakref.WeakKeyDictionary()


@asynccontextmanager
async def credential_slot(api_key):
    identifier = int.from_bytes(hashlib.sha256(api_key.encode()).digest()[:8], signed=True)
    loop_locks = _locks.setdefault(asyncio.get_running_loop(), {})
    async with loop_locks.setdefault(identifier, asyncio.Lock()):
        if engine.dialect.name != "postgresql":
            yield
            return
        # Dedicated session-level lock also coordinates the research-worker container.
        with engine.connect() as connection:
            acquired = False
            try:
                while not acquired:
                    acquired = connection.execute(
                        text("SELECT pg_try_advisory_lock(:identifier)"),
                        {"identifier": identifier},
                    ).scalar()
                    connection.commit()
                    if not acquired:
                        await asyncio.sleep(0.25)
                yield
            finally:
                if acquired:
                    connection.execute(text("SELECT pg_advisory_unlock(:identifier)"),
                                       {"identifier": identifier})
                    connection.commit()


class ZaiProvider(HTTPProvider):
    name = "zai"
    default_model = "glm-4.7-flash"
    supports_tool_calling = True
    supports_json_mode = True
    max_context_tokens = 200_000
    chat_url = "https://api.z.ai/api/paas/v4/chat/completions"

    async def validate_key(self, api_key):
        # Format acceptance only: saving a key must not trigger inference.
        return bool(api_key.strip()) and len(api_key.strip()) >= 12

    async def _completion(self, api_key, messages, tools, model):
        options = call_options.get()
        payload = {"model": model or self.default_model, "messages": messages,
                   "max_tokens": options.max_output_tokens, "stream": False,
                   "thinking": {"type": "disabled"}}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if options.json_mode or options.response_schema:
            payload["response_format"] = {"type": "json_object"}
        async with credential_slot(api_key):
            data = await self._post(self.chat_url, api_key, payload)
        message = data["choices"][0]["message"]
        blocks = []
        if message.get("content"):
            blocks.append(ContentBlock("text", text=message["content"]))
        for call in message.get("tool_calls") or []:
            function = call["function"]
            arguments = function["arguments"]
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                raise RuntimeError("zai returned invalid tool arguments")
            blocks.append(ContentBlock("tool_call", id=call["id"],
                                       name=function["name"], arguments=arguments))
        usage = data.get("usage") or {}
        return LLMProviderResult(
            content=message.get("content") or "", provider=self.name,
            model=data.get("model") or model or self.default_model,
            input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
            cache_read_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
            finish_reason=data["choices"][0].get("finish_reason"),
            turn=ProviderTurn("assistant", blocks),
        )

    async def chat(self, api_key, messages, model=None):
        return await self._completion(api_key, messages, [], model)

    async def tool_chat(self, api_key, turns, tools, model=None):
        messages = []
        for turn in turns:
            content = "\n".join(b.text for b in turn.content if b.type == "text" and b.text)
            calls = [b for b in turn.content if b.type == "tool_call"]
            results = [b for b in turn.content if b.type == "tool_result"]
            if content or calls:
                message = {"role": turn.role, "content": content or None}
                if calls:
                    message["tool_calls"] = [
                        {"id": b.id, "type": "function", "function": {
                            "name": wire_tool_name(b.name), "arguments": json.dumps(b.arguments)}}
                        for b in calls
                    ]
                messages.append(message)
            for result in results:
                messages.append({"role": "tool", "tool_call_id": result.id,
                                 "content": json.dumps(result.result, default=str)})
        definitions = [{"type": "function", "function": {
            "name": wire_tool_name(t.name), "description": t.description,
            "parameters": t.input_schema}} for t in tools]
        result = await self._completion(api_key, messages, definitions, model)
        names = {wire_tool_name(t.name): t.name for t in tools}
        from dataclasses import replace
        blocks = [replace(b, name=names.get(b.name, b.name)) if b.type == "tool_call" else b
                  for b in result.turn.content]
        return replace(result, turn=ProviderTurn("assistant", blocks))
