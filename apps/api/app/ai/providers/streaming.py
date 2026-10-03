"""Native SSE decoding and transport-specific fragmented response assembly.

Only visible text is emitted. Opaque reasoning/signatures stay in the assembled
provider response for encrypted tool-loop checkpoints.
"""
import json
from app.ai.providers.base import ProviderEvent, emit_provider_event


async def sse_json(lines):
    data = []
    async for line in lines:
        if not line:
            if data:
                value = "\n".join(data)
                data.clear()
                if value == "[DONE]":
                    return
                yield json.loads(value)
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        value = "\n".join(data)
        if value != "[DONE]":
            yield json.loads(value)


class StreamAssembler:
    def __init__(self, provider, api_key=""):
        self.provider = provider
        self.api_key = api_key
        self.data = {}
        self.blocks = {}
        self.arguments = {}
        self.finished = False

    async def feed(self, event):
        if event.get("error") or event.get("type") == "error" or event.get("event_type") == "error":
            import httpx
            from app.ai.providers.http_placeholders import _raise_provider_response_error
            _raise_provider_response_error(self.provider, httpx.Response(200, json=event), self.api_key)
        if self.provider == "anthropic":
            text = self._anthropic(event)
        elif self.provider == "gemini":
            text = self._gemini(event)
        else:
            text = self._openai(event)
        if text:
            await emit_provider_event(ProviderEvent("text_delta", text=text))

    def _openai(self, event):
        for key in ("id", "model", "usage"):
            if event.get(key) is not None:
                self.data[key] = event[key]
        choices = event.get("choices") or []
        if not choices:
            return None
        choice = choices[0]
        delta = choice.get("delta") or {}
        message = self.data.setdefault("message", {"role": "assistant", "content": ""})
        text = delta.get("content") or ""
        message["content"] += text
        if delta.get("reasoning_content"):
            message["reasoning_content"] = message.get("reasoning_content", "") + delta["reasoning_content"]
        for call in delta.get("tool_calls") or []:
            index = call["index"]
            target = self.blocks.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if call.get("id"):
                target["id"] = call["id"]
            function = call.get("function") or {}
            for field in ("name", "arguments"):
                target["function"][field] += function.get(field) or ""
        if choice.get("finish_reason") is not None:
            self.data["finish_reason"] = choice["finish_reason"]
            self.finished = True
        return text

    def _anthropic(self, event):
        kind = event.get("type")
        if kind == "message_start":
            self.data = event["message"]
        elif kind == "content_block_start":
            self.blocks[event["index"]] = dict(event["content_block"])
        elif kind == "content_block_delta":
            index = event["index"]
            block = self.blocks[index]
            delta = event["delta"]
            if delta["type"] == "input_json_delta":
                self.arguments[index] = self.arguments.get(index, "") + delta["partial_json"]
            else:
                field = {"text_delta": "text", "thinking_delta": "thinking", "signature_delta": "signature"}.get(delta["type"])
                if field:
                    block[field] = block.get(field, "") + delta.get(field, "")
                    if field == "text":
                        return delta.get(field)
        elif kind == "message_delta":
            self.data.update(event["delta"])
            self.data.setdefault("usage", {}).update(event.get("usage") or {})
        elif kind == "message_stop":
            self.finished = True
        return None

    def _gemini(self, event):
        kind = event.get("event_type")
        if kind in {"interaction.start", "interaction.created"}:
            self.data.update(event.get("interaction") or {})
        elif kind == "step.start":
            self.blocks[event["index"]] = dict(event.get("step") or {})
        elif kind == "step.delta":
            index = event["index"]
            delta = event.get("delta") or {}
            step = self.blocks.setdefault(index, {"type": "model_output", "content": []})
            if delta.get("type") == "text":
                content = step.setdefault("content", [])
                if not content or content[-1].get("type") != "text":
                    content.append({"type": "text", "text": ""})
                content[-1]["text"] += delta.get("text", "")
                return delta.get("text")
            if delta.get("arguments_delta"):
                self.arguments[index] = self.arguments.get(index, "") + delta["arguments_delta"]
            else:
                # Thought signatures/function identifiers are opaque continuation data.
                step.update({key: value for key, value in delta.items() if key != "type"})
        elif kind in {"interaction.complete", "interaction.completed"}:
            self.data.update(event.get("interaction") or {})
            self.finished = True
        return None

    def result(self):
        if self.provider == "anthropic":
            incomplete = not self.finished or self.data.get("stop_reason") in {"max_tokens", "incomplete"}
            if incomplete:
                self.blocks = {key: block for key, block in self.blocks.items() if block.get("type") != "tool_use"}
            for index, raw in self.arguments.items():
                if index in self.blocks:
                    # Anthropic emits an empty input delta for zero-argument
                    # tools. Keep the initial input object in that case.
                    if raw.strip():
                        self.blocks[index]["input"] = json.loads(raw)
            self.data["content"] = [self.blocks[key] for key in sorted(self.blocks)]
            if not self.finished:
                self.data["stop_reason"] = "incomplete"
        elif self.provider == "gemini":
            if not self.finished or self.data.get("status") == "incomplete":
                self.blocks = {key: block for key, block in self.blocks.items() if block.get("type") != "function_call"}
            for index, raw in self.arguments.items():
                if index in self.blocks:
                    self.blocks[index]["arguments"] = json.loads(raw)
            if self.blocks:
                self.data["steps"] = [self.blocks[key] for key in sorted(self.blocks)]
            if not self.finished:
                self.data["status"] = "incomplete"
        else:
            message = self.data.pop("message", {"content": ""})
            if self.blocks and self.data.get("finish_reason") not in {None, "length", "incomplete"}:
                message["tool_calls"] = [self.blocks[key] for key in sorted(self.blocks)]
            self.data["choices"] = [{"message": message, "finish_reason": self.data.pop("finish_reason", "incomplete")}]
        return self.data
