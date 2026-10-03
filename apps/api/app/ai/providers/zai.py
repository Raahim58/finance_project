"""Direct Z.ai transport; one in-flight request per credential across processes."""

import asyncio
import hashlib
import json
import weakref
from contextlib import asynccontextmanager

from sqlalchemy import text

from app.ai.providers.base import ContentBlock, LLMProviderResult, ProviderTurn, call_options
from app.ai.providers.http_placeholders import OpenAICompatibleProvider, wire_tool_name
from app.db.session import engine

_locks = weakref.WeakKeyDictionary()


@asynccontextmanager
async def credential_slot(api_key):
    from datetime import timedelta
    from uuid import uuid4
    from sqlalchemy import select, delete
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.models.assistant_workspace import ProviderQueueEntry
    from app.models.assistant_execution import now, AssistantExecution
    from app.services.assistant_diagnostics import execution_id
    from app.ai.providers.base import ProviderEvent, emit_provider_event, ProviderQueueTimeout
    import time
    digest = hashlib.sha256(api_key.encode()).hexdigest()
    identifier = int.from_bytes(bytes.fromhex(digest)[:8], signed=True)
    request_id = str(uuid4())
    execution = execution_id.get()
    priority = 0 if execution else 1
    started = time.monotonic()
    timeout = settings.assistant_queue_timeout_seconds
    await emit_provider_event(ProviderEvent("waiting"))

    def record_wait():
        if execution:
            with SessionLocal.begin() as db:
                row = db.get(AssistantExecution, execution, with_for_update=True)
                accounting = json.loads(row.accounting_json)
                accounting["queue_ms"] = accounting.get("queue_ms", 0) + round((time.monotonic() - started) * 1000)
                row.accounting_json = json.dumps(accounting)

    if engine.dialect.name != "postgresql":
        queue = _locks.setdefault(asyncio.get_running_loop(), {}).setdefault(identifier, [])
        entry = (priority, started, request_id)
        queue.append(entry)
        try:
            try:
                async with asyncio.timeout(timeout):
                    while min(queue) != entry or any(item[0] == -1 for item in queue):
                        await asyncio.sleep(0.02)
            except TimeoutError as exc:
                raise ProviderQueueTimeout("Credential queue wait expired") from exc
            queue.remove(entry)
            running = (-1, started, request_id)
            queue.append(running)
            record_wait()
            try:
                yield
            finally:
                queue.remove(running)
        finally:
            if entry in queue:
                queue.remove(entry)
        return
    with SessionLocal.begin() as db:
        db.add(ProviderQueueEntry(id=request_id, credential_hash=digest, priority=priority,
                                 expires_at=now() + timedelta(seconds=timeout + 10)))
    connection = None
    acquired = False
    try:
        try:
            async with asyncio.timeout(timeout):
                while not acquired:
                    with SessionLocal.begin() as db:
                        db.execute(delete(ProviderQueueEntry).where(ProviderQueueEntry.expires_at < now()))
                        first = db.scalar(select(ProviderQueueEntry.id).where(ProviderQueueEntry.credential_hash == digest)
                                          .order_by(ProviderQueueEntry.priority, ProviderQueueEntry.created_at, ProviderQueueEntry.id).limit(1))
                    if first == request_id:
                        connection = engine.connect()
                        acquired = connection.execute(text("SELECT pg_try_advisory_lock(:identifier)"), {"identifier": identifier}).scalar()
                        connection.commit()
                        if not acquired:
                            connection.close()
                            connection = None
                    if not acquired:
                        await asyncio.sleep(0.25)
        except TimeoutError as exc:
            raise ProviderQueueTimeout("Credential queue wait expired") from exc
        with SessionLocal.begin() as db:
            db.execute(delete(ProviderQueueEntry).where(ProviderQueueEntry.id == request_id))
        record_wait()
        yield
    finally:
        if connection is not None:
            try:
                if acquired:
                    connection.execute(text("SELECT pg_advisory_unlock(:identifier)"), {"identifier": identifier})
                    connection.commit()
            finally:
                connection.close()
        with SessionLocal.begin() as db:
            db.execute(delete(ProviderQueueEntry).where(ProviderQueueEntry.id == request_id))


class ZaiProvider(OpenAICompatibleProvider):
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
                   "thinking": ({"type": "enabled", "clear_thinking": not any(m.get("reasoning_content") for m in messages)} if options.thinking else {"type": "disabled"})}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if options.json_mode or options.response_schema:
            payload["response_format"] = {"type": "json_object"}
        async with credential_slot(api_key):
            data = await self._send(self.chat_url, api_key, payload)
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
            reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            finish_reason=data["choices"][0].get("finish_reason"),
            turn=ProviderTurn("assistant", blocks, {"reasoning_content": message.get("reasoning_content")}),
        )

    async def chat(self, api_key, messages, model=None):
        return await self._completion(api_key, messages, [], model)
