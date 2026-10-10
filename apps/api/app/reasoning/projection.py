"""Single model projection; canonical records retain complete provenance."""
from __future__ import annotations

import hashlib
import json
import math
import re

VERSION = "phase8-projection-1"
OMIT = {"allowed_numeric_tokens", "deterministic_fallback", "numeric_allowlist",
        "receipt", "provenance", "dependency_hash", "reused", "canonical_evidence", "question", "built_at", "section_duration_ms"}


def encode(value: object) -> str:
    return json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def estimate_tokens(value: object) -> int:
    from app.ai.token_counting import text_estimate
    amount = text_estimate(value if isinstance(value, str) else encode(value))
    return amount if amount is not None else legacy_estimate_tokens(value)


def legacy_estimate_tokens(value: object) -> int:
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


class BudgetExceeded(ValueError):
    pass


