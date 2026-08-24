"""Deterministic Phase 6 event classification and scoring rules."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal


DETECTION_VERSION = "deterministic-v2"
TOKEN_RE = re.compile(r"[a-z0-9]+")

EVENT_RULES: tuple[tuple[str, str | None, tuple[str, ...]], ...] = (
    ("insider_transaction", "insider_activity", ("disclosure of interest", "substantial shareholder", "intimation of shareholding", "insider transaction", "director shareholding")),
    ("dividend", None, ("cash dividend", "interim dividend", "final dividend", "dividend entitlement", "dividend payment", "credit of dividend", "interim distribution", "final distribution", "dividend distribution")),
    ("earnings", "earnings", ("financial results", "quarterly results", "annual results", "half yearly results", "half year results", "earnings release", "profit after tax", "quarterly financial statements", "annual financial statements", "half yearly financial statements", "quarterly report", "annual report", "half yearly report", "half yearly accounts", "quarterly accounts")),
    ("corporate_action", None, ("rights issue", "right issue", "right shares", "bonus shares", "bonus share", "share split", "stock split", "share buyback", "merger", "acquisition", "intention to acquire", "scheme of arrangement", "allotment of shares", "issuance of shares", "paid up capital", "farm in transaction", "sub divided ordinary shares", "sub division of shares", "voluntarily winding up", "request for delisting")),
    ("financing", "financing", ("issuance of sukuk", "sukuk issuance", "term finance certificate", "project financing", "financing agreement", "long term loan", "debt issuance", "commercial paper")),
    ("governance", "governance", ("appointment of director", "appointment of independent director", "appointment of chairperson", "appointment of chairman", "appointment of chief executive", "appointment of ceo", "appointment of chief financial officer", "appointment of cfo", "appointment of company secretary", "resignation of director", "resignation of independent director", "re appointment of chief executive", "re appointment of president", "change of director", "change of chief executive", "change of chief financial officer", "change of cfo", "change of management", "change of chairman", "head of internal audit", "latest list of directors", "demise of chief financial officer")),
    ("corporate_calendar", "corporate_calendar", ("board meeting", "board of directors meeting", "closed period", "annual general meeting", "extraordinary general meeting", "extra ordinary general meeting", "election of directors", "general meetings briefing sessions", "postal ballot", "notice under section 159", "notice u s 159", "meeting of the board of directors", "notice of eogm", "notice of agm", "resolution passed in agm", "resolution passed in eogm", "holding the agm", "notice of book closure")),
    ("briefing_research", "company_research", ("corporate briefing", "presentation of cbs", "cbs presentation", "video recording", "analyst briefing", "investor presentation", "results presentation")),
    ("compliance_disclosure", "compliance", ("shariah disclosure", "shariah screening", "shariah compliant disclosure", "shariah compliance disclosure", "code of corporate governance", "compliance certificate")),
    ("market_notice", "market_activity", ("unusual movement in price", "unusual movement in volume", "unusual movement in price or volume", "unusual movement in price volume", "clarification regarding media", "response to a news item", "disclosure in response to a news item")),
    ("operational_disruption", "operations", ("plant shutdown", "production shutdown", "operations suspended", "production suspended", "unplanned outage", "force majeure", "factory fire", "plant fire", "explosion", "operational disruption")),
    ("geopolitical_risk", "geopolitical_risk", ("armed conflict", "border tensions", "geopolitical tensions", "trade sanctions", "economic sanctions", "military strike", "declaration of war", "civil unrest", "strait of hormuz", "hormuz", "counter terrorism designation", "sanctions list", "missile attack", "vessel attacked")),
    ("rates", "interest_rates", ("policy rate", "key rate", "interest rate", "basis points", "monetary policy", "discount rate", "kibor", "rate hike", "rate cut", "bond yield", "treasury yield")),
    ("fx", "foreign_exchange", ("exchange rate", "foreign exchange", "currency depreciation", "currency appreciation", "rupee depreciation", "rupee appreciation", "usd pkr", "interbank rupee", "currency devaluation")),
    ("oil_commodities", "oil_commodities", ("oil discovery", "gas discovery", "oil production", "gas production", "crude oil", "natural gas", "production commencement", "commencement of production", "oil price", "gas price", "commodity price", "working interest", "oil reserve", "oil spill", "oil tanker", "lng", "petroleum", "copper price", "gold price", "wheat price")),
    ("operational_development", "operations", ("commencement of operations", "production started", "production begins", "capacity expansion", "capacity enhancement", "contract awarded", "award of contract", "joint venture", "strategic partnership", "launch of", "new project", "commercial operations", "memorandum of understanding", "production and sales data", "business plan", "annual budget")),
    ("regulation", "regulation", ("regulatory order", "policy notification", "new regulation", "licence suspended", "license suspended", "tariff determination", "tax amendment", "secp order", "regulatory amendment", "court order", "government notification")),
)

EVENT_PATTERNS: tuple[tuple[str, str | None, tuple[re.Pattern[str], ...]], ...] = (
    ("earnings", "earnings", (
        re.compile(r"\b(?:transmission of )?(?:1st |2nd |3rd |4th )?quarterly (?:financial )?(?:report|statements?|accounts?)\b"),
        re.compile(r"\b(?:transmission of )?(?:half[- ]yearly|six months?) (?:financial )?(?:report|statements?|accounts?|results?)\b"),
        re.compile(r"\b(?:transmission of )?annual (?:financial )?(?:report|statements?|accounts?|results?)\b"),
        re.compile(r"\bfinancial statements? for (?:the )?(?:period|quarter|year|nine months)\b"),
        re.compile(r"\btransmission of (?:the )?(?:first|second|third|fourth) quarter report\b"),
    )),
    ("governance", "governance", (
        re.compile(r"\b(?:re appointment|appointment|resignation|cessation|change) of (?:the )?(?:independent )?(?:chairman|chairperson|president|director|chief executive(?: officer)?|ceo|chief financial officer|cfo|company secretary|head of internal audit)\b"),
    )),
    ("insider_transaction", "insider_activity", (
        re.compile(r"\b(?:purchase|sale|transfer) of shares? by (?:a )?(?:director|ceo|executive|substantial shareholder)\b"),
    )),
    ("market_notice", "market_activity", (
        re.compile(r"\bclarification regarding (?:certain )?(?:media|news|social media) reports?\b"),
    )),
)

MATERIALITY_ORDER = {"unknown": 0, "low": 1, "medium": 2, "high": 3}


@dataclass(frozen=True)
class Magnitude:
    value: Decimal
    unit: str
    direction: str | None
    matched_text: str


@dataclass(frozen=True)
class EventDetection:
    event_type: str
    factor: str | None
    classification_status: str
    matched_signals: tuple[str, ...]
    magnitude: Magnitude | None


def normalized_tokens(text: str) -> tuple[str, ...]:
    return tuple(TOKEN_RE.findall(text.casefold()))


def title_similarity(left: str, right: str) -> float:
    a, b = set(normalized_tokens(left)), set(normalized_tokens(right))
    return len(a & b) / len(a | b) if a and b else 0.0


def detect_magnitude(text: str) -> Magnitude | None:
    patterns = (
        (re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:basis points|bps)\b", re.I), "bps"),
        (re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:%|percent)\b", re.I), "percent"),
    )
    for pattern, unit in patterns:
        match = pattern.search(text)
        if match:
            prefix = text[max(0, match.start() - 48):match.start()].casefold()
            direction = None
            if any(word in prefix for word in ("raise", "raised", "increase", "increased", "hike", "up by")):
                direction = "increase"
            elif any(word in prefix for word in ("cut", "decrease", "decreased", "reduction", "down by")):
                direction = "decrease"
            return Magnitude(Decimal(match.group(1)), unit, direction, match.group(0))
    return None


def classify_event(text: str) -> EventDetection:
    normalized = " ".join(normalized_tokens(text))
    matches: list[tuple[int, int, str, str | None, tuple[str, ...]]] = []
    for priority, (event_type, factor, signals) in enumerate(EVENT_RULES):
        found = tuple(signal for signal in signals if signal in normalized)
        if found:
            matches.append((len(found), -priority, event_type, factor, found))
    offset = len(EVENT_RULES)
    for pattern_priority, (event_type, factor, patterns) in enumerate(EVENT_PATTERNS):
        found_patterns = tuple(pattern.pattern for pattern in patterns if pattern.search(normalized))
        if found_patterns:
            matches.append((len(found_patterns) + 1, -(offset + pattern_priority), event_type, factor, found_patterns))
    if not matches:
        return EventDetection("unclassified", None, "unclassified", (), detect_magnitude(text))
    _, _, event_type, factor, found = max(matches)
    return EventDetection(event_type, factor, "classified", found, detect_magnitude(text))


def event_materiality(detection: EventDetection, text: str, *, has_direct_subject: bool) -> str:
    normalized = " ".join(normalized_tokens(text))
    magnitude = detection.magnitude.value if detection.magnitude else None
    if detection.event_type == "unclassified":
        return "unknown"
    if detection.event_type == "rates":
        if detection.magnitude is None or detection.magnitude.unit != "bps":
            return "unknown"
        return "high" if magnitude >= 100 else "medium" if magnitude >= 25 else "low"
    if detection.event_type == "fx":
        if detection.magnitude is None or detection.magnitude.unit != "percent":
            return "unknown"
        return "high" if magnitude >= 5 else "medium" if magnitude >= 2 else "low"
    if detection.event_type == "dividend":
        if detection.magnitude and detection.magnitude.unit == "percent":
            return "high" if magnitude >= 50 else "medium" if magnitude >= 15 else "low"
        return "medium" if has_direct_subject else "unknown"
    if detection.event_type == "corporate_action":
        return "high" if any(signal in normalized for signal in ("merger", "acquisition", "rights issue", "scheme of arrangement", "share buyback")) else "medium"
    if detection.event_type == "operational_disruption":
        return "high" if any(signal in normalized for signal in ("explosion", "fire", "force majeure", "shutdown")) else "medium"
    if detection.event_type == "regulation":
        return "high" if any(signal in normalized for signal in ("licence suspended", "license suspended", "ban", "regulatory order")) else "medium"
    if detection.event_type == "oil_commodities":
        return "medium" if has_direct_subject else "unknown"
    if detection.event_type == "geopolitical_risk":
        return "high" if any(signal in normalized for signal in ("war", "military strike", "armed conflict", "sanctions")) else "medium"
    if detection.event_type == "earnings":
        return "high" if any(signal in normalized for signal in ("profit warning", "material loss", "default")) else "medium"
    if detection.event_type == "governance":
        return "medium" if any(signal in normalized for signal in ("chief executive", "ceo", "chief financial officer", "cfo", "chairman")) else "low"
    if detection.event_type in {"insider_transaction", "corporate_calendar", "briefing_research", "compliance_disclosure", "market_notice"}:
        return "low"
    if detection.event_type == "financing":
        return "medium" if has_direct_subject else "unknown"
    if detection.event_type == "operational_development":
        return "medium" if has_direct_subject else "unknown"
    return "unknown"


def event_confidence(
    detection: EventDetection,
    *,
    primary_source: bool,
    has_direct_subject: bool,
    independent_source_count: int,
    prototype_agreement: bool,
) -> Decimal:
    score = Decimal("0.45")
    if detection.classification_status == "classified":
        score += Decimal("0.15")
    if primary_source:
        score += Decimal("0.12")
    if has_direct_subject:
        score += Decimal("0.12")
    if independent_source_count >= 2:
        score += Decimal("0.08")
    if detection.magnitude:
        score += Decimal("0.04")
    if prototype_agreement:
        score += Decimal("0.04")
    return min(Decimal("0.99"), score).quantize(Decimal("0.000001"))


def event_freshness(occurred_at: datetime, *, now: datetime | None = None) -> tuple[Decimal, str]:
    reference = now or datetime.now(UTC)
    occurred = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC)
    age_days = max(0.0, (reference - occurred).total_seconds() / 86400)
    score = Decimal(str(math.exp(-age_days / 90))).quantize(Decimal("0.000001"))
    status = "fresh" if age_days <= 7 else "recent" if age_days <= 90 else "stale"
    return score, status


def cluster_identity(event_type: str, occurred_at: datetime, subjects: tuple[str, ...], title: str) -> str:
    day = occurred_at.date().isoformat()
    signature = " ".join(sorted(set(normalized_tokens(title))))
    raw = f"{event_type}|{day}|{'|'.join(sorted(subjects))}|{signature}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
