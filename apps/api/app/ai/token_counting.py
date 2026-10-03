"""Local tokenization and conditional provider preflight; never generation."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from functools import lru_cache
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parents[2] / "storage/tokenizers/glm45"
ASSET_HASHES = {
    "tokenizer.json": "9340665016419c825c4bdabbcc9acc43b7ca2c68ce142724afa829abb1be5efd",
    "chat_template.jinja": "44f815868bf02fa458dd2f741a338046f4bf45f398eb6d067766726b9d96cce3",
}
GLM_MODELS = {"glm-4.5-flash", "glm-4.5-air", "glm-4.5"}


@lru_cache(maxsize=1)
def local_assets():
    from tokenizers import Tokenizer
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    for name, expected in ASSET_HASHES.items():
        if hashlib.sha256((ASSET_DIR / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Tokenizer asset checksum mismatch")
    environment = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    environment.filters["tojson"] = lambda value, **kw: json.dumps(value, **kw)
    return (Tokenizer.from_file(str(ASSET_DIR / "tokenizer.json")),
            environment.from_string((ASSET_DIR / "chat_template.jinja").read_text()))


def text_estimate(text: str) -> int | None:
    try:
        tokenizer, _ = local_assets()
    except (FileNotFoundError, ImportError):
        return None
    return math.ceil(len(tokenizer.encode(text, add_special_tokens=False).ids) * 1.05)


def local_input_count(provider: str, payload: dict) -> tuple[int, str]:
    from app.reasoning.projection import legacy_estimate_tokens
    if provider != "zai" or payload.get("model") not in GLM_MODELS:
        return legacy_estimate_tokens(payload), "legacy_conservative_estimate"
    try:
        tokenizer, template = local_assets()
    except (FileNotFoundError, ImportError):
        return legacy_estimate_tokens(payload), "local_tokenizer_unavailable"
    messages = copy.deepcopy(payload.get("messages", []))
    # The server parses JSON function arguments before rendering its template.
    for message in messages:
        for call in message.get("tool_calls") or []:
            function = call["function"]
            if isinstance(function.get("arguments"), str):
                function["arguments"] = json.loads(function["arguments"])
        if isinstance(message.get("content"), list) and any(
            block.get("type") != "text" for block in message["content"] if isinstance(block, dict)
        ):
            return legacy_estimate_tokens(payload), "multimodal_conservative_estimate"
    rendered = template.render(messages=messages, tools=payload.get("tools", []),
                               add_generation_prompt=True,
                               enable_thinking=payload.get("thinking", {}).get("type") != "disabled")
    # Hosted template can differ from the published template: retain 5% margin.
    count = len(tokenizer.encode(rendered, add_special_tokens=False).ids)
    return math.ceil(count * 1.05), "glm45_local_template_plus_5pct"


async def preflight_count(provider, api_key, payload, *, input_limit, remaining_input):
    started = time.perf_counter()
    count, method = local_input_count(provider.name, payload)
    metadata = {"local_estimated_input_tokens": count, "input_count_method": method}
    boundary = min(input_limit, remaining_input)
    # Confirm borderline estimates (including apparent oversize), not every call.
    if provider.name == "anthropic" and count >= boundary * 0.8:
        try:
            count = await provider.count_input_tokens(api_key, payload)
            metadata.update(input_count_method="anthropic_count_tokens", provider_counted_input_tokens=count)
        except Exception as exc:
            # Cancellation is a BaseException and must propagate. No retry or
            # bypass: retain the conservative reservation if counting fails.
            metadata["input_count_error"] = type(exc).__name__
    metadata["input_count_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return count, metadata
