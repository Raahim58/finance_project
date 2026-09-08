"""Single model projection; canonical records retain complete provenance."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass

VERSION = "phase8-projection-1"
OMIT = {"allowed_numeric_tokens", "deterministic_fallback", "numeric_allowlist",
        "receipt", "provenance", "dependency_hash", "reused", "canonical_evidence", "question", "built_at", "section_duration_ms"}


def encode(value: object) -> str:
    return json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def estimate_tokens(value: object) -> int:
    # Offline estimate: punctuation tokens plus short lexical pieces, with 25% margin.
    # Provider-reported usage remains separate; this is not an exact tokenizer.
    pieces = re.findall(r"[A-Za-z0-9_]+|[^A-Za-z0-9_\s]", encode(value))
    return math.ceil(sum(max(1, math.ceil(len(piece.encode("utf-8")) / 3)) for piece in pieces) * 1.25)


def project(value: object) -> dict[str, object]:
    records: dict[str, object] = {}
    seen: dict[str, str] = {}
    duplicates = 0

    def visit(item: object):
        nonlocal duplicates
        if isinstance(item, dict):
            cleaned = {k: visit(v) for k, v in item.items() if k not in OMIT and v is not None and v != [] and v != {}}
            # Intern repeated nontrivial objects, including nested event subjects/sources.
            if len(encode(cleaned)) < 250:
                return cleaned
            digest = hashlib.sha256(encode(cleaned).encode()).hexdigest()[:24]
            if digest in seen:
                duplicates += 1
            else:
                seen[digest] = digest
                records[digest] = cleaned
            return {"$ref": digest}
        if isinstance(item, (list, tuple)):
            result = []
            keys = set()
            for child in item:
                projected = visit(child)
                key = encode(projected)
                if key not in keys:
                    result.append(projected)
                    keys.add(key)
            return result
        return item

    root = visit(value)
    return {"projection_version": VERSION, "root": root, "records": records,
            "counts": {"unique_records": len(records), "duplicate_records_removed": duplicates,
                       "omitted_evidence": 0}}


def bounded_history(history: list[dict[str, str]], ceiling: int = 2000):
    result = []
    used = 0
    for message in reversed(history):
        size = estimate_tokens(message)
        if used + size > ceiling:
            break
        result.append(message)
        used += size
    return list(reversed(result))


class BudgetExceeded(ValueError):
    pass


@dataclass
class InferenceBudget:
    per_call: int = 20_000
    execution: int = 48_000
    spent: int = 0
    output_reserve: int = 4096
    recovery_reserve: int = 8000

    def reserve(self, messages: object, *, recovery: bool, provider_limit: int) -> int:
        amount = estimate_tokens(messages)
        limit = min(8000 if recovery else self.per_call, provider_limit - self.output_reserve)
        remaining_reserve = 0 if recovery else self.recovery_reserve
        if amount > limit or self.spent + amount + remaining_reserve > self.execution:
            raise BudgetExceeded(f"Safe evidence compaction cannot fit: estimated input {amount}, call ceiling {limit}, execution remaining {self.execution - self.spent - remaining_reserve}")
        self.spent += amount
        return amount
