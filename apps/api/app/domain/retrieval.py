"""Pure retrieval planning, ranking, and evidence-quality rules."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta


TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%-]*")
NUMBER_RE = re.compile(r"^(?:\(?[-+]?\d[\d,]*(?:\.\d+)?\)?%?)$")
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "was",
    "were", "what", "when", "where", "which", "who", "why", "with",
}

DOCUMENT_TYPE_ALIASES = {
    "announcement": "announcement",
    "announcements": "announcement",
    "company_announcement": "announcement",
    "psx_announcement": "announcement",
    "psx_notice": "announcement",
    "annual": "annual_report",
    "annual_report": "annual_report",
    "quarterly": "quarterly_report",
    "quarterly_report": "quarterly_report",
    "interim_report": "quarterly_report",
    "research": "research_report",
    "research_report": "research_report",
    "news": "news",
    "event": "event",
    "events": "event",
    "macro": "macro_report",
    "macro_report": "macro_report",
    "policy": "policy_document",
    "policy_document": "policy_document",
}

HORIZON_DAYS = {
    "week": 7,
    "month": 30,
    "quarter": 90,
    "six_months": 183,
    "year": 365,
}


@dataclass(frozen=True)
class RetrievalPlan:
    query: str
    query_tokens: tuple[str, ...]
    symbols: tuple[str, ...]
    sectors: tuple[str, ...]
    document_types: tuple[str, ...]
    date_from: date | None
    date_to: date | None
    portfolio_id: str | None
    limit: int


def tokenize(text: str, *, meaningful: bool = False) -> list[str]:
    tokens = [match.group(0).casefold() for match in TOKEN_RE.finditer(text)]
    if meaningful:
        return [token for token in tokens if token not in STOP_WORDS]
    return tokens


def canonical_document_type(value: str) -> str:
    normalized = "_".join(value.strip().casefold().replace("-", " ").split())
    return DOCUMENT_TYPE_ALIASES.get(normalized, normalized)


def build_retrieval_plan(
    *,
    query: str,
    symbols: Sequence[str] | None,
    sectors: Sequence[str] | None,
    document_types: Sequence[str] | None,
    date_from: date | None,
    date_to: date | None,
    time_horizon: str | None,
    portfolio_id: str | None,
    limit: int,
    today: date | None = None,
) -> RetrievalPlan:
    effective_to = date_to
    effective_from = date_from
    if time_horizon and time_horizon != "all":
        anchor = date_to or today or date.today()
        effective_to = anchor
        effective_from = anchor - timedelta(days=HORIZON_DAYS[time_horizon])
    return RetrievalPlan(
        query=query.strip(),
        query_tokens=tuple(dict.fromkeys(tokenize(query, meaningful=True))),
        symbols=tuple(dict.fromkeys(item.strip().upper() for item in symbols or () if item.strip())),
        sectors=tuple(dict.fromkeys(item.strip() for item in sectors or () if item.strip())),
        document_types=tuple(dict.fromkeys(canonical_document_type(item) for item in document_types or () if item.strip())),
        date_from=effective_from,
        date_to=effective_to,
        portfolio_id=portfolio_id,
        limit=limit,
    )


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def lexical_score(query_tokens: Sequence[str], chunk_text: str) -> float:
    """Return bounded term coverage with a small exact-phrase reward."""

    if not query_tokens:
        return 0.0
    chunk_tokens = tokenize(chunk_text, meaningful=True)
    if not chunk_tokens:
        return 0.0
    chunk_set = set(chunk_tokens)
    coverage = len(set(query_tokens).intersection(chunk_set)) / len(set(query_tokens))
    phrase = " ".join(query_tokens)
    compact_chunk = " ".join(chunk_tokens)
    phrase_bonus = 0.15 if len(query_tokens) > 1 and phrase in compact_chunk else 0.0
    return min(1.0, coverage + phrase_bonus)


def reciprocal_rank_fusion(
    rankings: Iterable[Sequence[str]], *, k: int = 60
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + (1.0 / (k + rank))
    return scores


def classify_chunk_content(text: str) -> str:
    tokens = tokenize(text)
    if not tokens:
        return "boilerplate"
    normalized = " ".join(tokens)
    boilerplate_signals = (
        "table of contents",
        "all rights reserved",
        "intentionally left blank",
        "registered office",
    )
    if any(signal in normalized for signal in boilerplate_signals):
        return "boilerplate"
    numeric_share = sum(1 for token in tokens if NUMBER_RE.match(token)) / len(tokens)
    if numeric_share >= 0.35:
        return "table"
    if numeric_share >= 0.15:
        return "mixed"
    return "narrative"


def source_tier(source_name: str, *, owner_user_id: str | None = None) -> int:
    if owner_user_id:
        return 4
    normalized = source_name.casefold()
    primary = (
        "pakistan stock exchange", "psx financials", "state bank of pakistan",
        "sbp", "securities and exchange commission", "secp", "government of pakistan",
        "pakistan bureau of statistics", "world bank", "international monetary fund",
    )
    established = ("mettis", "dawn", "business recorder", "reuters", "bloomberg")
    if any(value in normalized for value in primary):
        return 1
    if any(value in normalized for value in established):
        return 2
    return 3


def freshness_adjustment(published: date | None, *, today: date | None = None) -> float:
    if published is None:
        return 0.0
    age_days = max(0, ((today or date.today()) - published).days)
    # Bounded below one RRF rank step; relevance always remains primary.
    return 0.0015 * math.exp(-age_days / 180)


def source_adjustment(tier: int) -> float:
    return {1: 0.0012, 2: 0.0008, 3: 0.0003, 4: 0.0}.get(tier, 0.0)


def content_adjustment(content_type: str, *, table_intent: bool) -> float:
    if content_type == "boilerplate":
        return -0.02
    if content_type == "table" and not table_intent:
        return -0.01
    if content_type == "mixed" and not table_intent:
        return -0.002
    return 0.0


def has_table_intent(query: str) -> bool:
    normalized = " ".join(tokenize(query, meaningful=True))
    signals = ("show table", "find table", "statement", "balance sheet", "income statement")
    return any(signal in normalized for signal in signals)
