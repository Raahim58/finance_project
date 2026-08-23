import re
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from html import unescape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import DocumentChunk
from app.models.evidence import DiscoveryCandidate
from app.models.workstation import Event, EventEntityLink, EventSource, Instrument, InstrumentAlias


@dataclass(frozen=True)
class SourcedCompanyEvent:
    event: Event
    sources: tuple[EventSource, ...]


CORPORATE_SUFFIX = re.compile(
    r"\s+(?:limited|limted|ltd\.?|plc|modaraba|reit)\s*$",
    flags=re.IGNORECASE,
)
EXPLICIT_TICKER_PATTERNS = (
    re.compile(r"\$([A-Z][A-Z0-9.-]{1,29})\b"),
    re.compile(r"\bPSX\s*:\s*([A-Z][A-Z0-9.-]{1,29})\b", re.IGNORECASE),
    re.compile(r"\b([A-Z][A-Z0-9.-]{1,29})\.PSX\b", re.IGNORECASE),
    re.compile(r"\(([A-Z][A-Z0-9.-]{1,29})\s*:\s*PSX\)", re.IGNORECASE),
)
BARE_TICKER = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9.-]{2,9})(?![A-Za-z0-9])")
PAKISTAN_MARKET_CONTEXT = (
    "pakistan",
    "pakistani",
    "karachi stock",
    "psx",
    "kse",
    "pkr",
    "rupee",
)
SECURITY_CONTEXT = (
    "share price",
    "shares",
    "stock",
    "listed company",
    "financial results",
    "earnings",
    "dividend",
    "profit after tax",
    "quarter ended",
    "annual report",
    "corporate briefing",
    "material information",
)


def _normalized_phrase(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", unescape(value).casefold()))


def _name_variants(value: str) -> set[str]:
    candidate = unescape(value).strip()
    full_name = _normalized_phrase(candidate)
    base_name = _normalized_phrase(CORPORATE_SUFFIX.sub("", candidate).strip())
    variants = {full_name} if len(full_name) >= 4 else set()
    if len(base_name.split()) >= 2:
        variants.add(base_name)
    return variants


def _explicit_tickers(text: str) -> set[str]:
    return {
        match.group(1).upper()
        for pattern in EXPLICIT_TICKER_PATTERNS
        for match in pattern.finditer(text)
    }


def _contextual_tickers(text: str, symbols: set[str]) -> set[str]:
    without_markup = re.sub(r"<[^>]+>", " ", unescape(text))
    normalized = without_markup.casefold()
    if not any(term in normalized for term in PAKISTAN_MARKET_CONTEXT):
        return set()
    if not any(term in normalized for term in SECURITY_CONTEXT):
        return set()
    # PSX is normally the exchange reference in this context, not PSX Limited.
    return ({match.group(1) for match in BARE_TICKER.finditer(without_markup)} & symbols) - {"PSX"}


def contains_explicit_instrument_reference(
    text: str,
    symbol: str,
    names: tuple[str, ...],
) -> bool:
    """Require issuer identity or explicit ticker notation, not a bare word/acronym."""

    normalized_symbol = symbol.strip().upper()
    if normalized_symbol in _explicit_tickers(text):
        return True

    normalized = f" {_normalized_phrase(text)} "
    for name in names:
        for variant in _name_variants(name or ""):
            if variant.upper() != normalized_symbol and f" {variant} " in normalized:
                return True
    return False


def sourced_company_events(db: Session, instrument: Instrument) -> list[SourcedCompanyEvent]:
    """Return observed company events, validating legacy news links from stored text only."""

    link_rows = db.execute(
        select(EventEntityLink.event_id, EventEntityLink.link_method).where(
            EventEntityLink.entity_type == "instrument",
            func.upper(EventEntityLink.entity_key) == instrument.symbol.upper(),
        )
    ).all()
    event_ids = list(dict.fromkeys(row.event_id for row in link_rows))
    rebuilt_event_ids = {
        row.event_id for row in link_rows if row.link_method.startswith("stored_")
    }
    if not event_ids:
        return []

    events = list(
        db.scalars(
            select(Event)
            .where(Event.id.in_(event_ids))
            .order_by(Event.occurred_at.desc())
        )
    )
    sources_by_event: dict[str, list[EventSource]] = {}
    document_events: dict[str, set[str]] = {}
    source_rows = db.scalars(
        select(EventSource)
        .where(
            EventSource.event_id.in_(event_ids),
            ~func.lower(EventSource.source_name).contains("demo"),
            ~func.lower(EventSource.source_url).like("demo://%"),
        )
        .order_by(EventSource.published_at.desc(), EventSource.source_name.asc())
    )
    for source in source_rows:
        sources_by_event.setdefault(source.event_id, []).append(source)
        if source.document_id:
            document_events.setdefault(source.document_id, set()).add(source.event_id)

    text_by_event = {event.id: event.title for event in events}
    if document_events:
        for document_id, chunk_text in db.execute(
            select(DocumentChunk.document_id, DocumentChunk.chunk_text).where(
                DocumentChunk.document_id.in_(document_events)
            )
        ):
            for event_id in document_events[document_id]:
                text_by_event[event_id] += f"\n{chunk_text}"

    aliases = tuple(
        db.scalars(
            select(InstrumentAlias.alias).where(InstrumentAlias.instrument_id == instrument.id)
        )
    )
    result: list[SourcedCompanyEvent] = []
    for event in events:
        sources = tuple(sources_by_event.get(event.id, ()))
        if not sources:
            continue
        if event.event_type == "news" and event.id not in rebuilt_event_ids and not contains_explicit_instrument_reference(
            text_by_event[event.id], instrument.symbol, (instrument.name, *aliases)
        ):
            continue
        result.append(SourcedCompanyEvent(event=event, sources=sources))
    return result


def _stored_news_text(db: Session, events: list[Event]) -> dict[str, str]:
    event_ids = [event.id for event in events]
    parts: dict[str, list[str]] = {event.id: [event.title] for event in events}
    for candidate, source_event_id in db.execute(
        select(DiscoveryCandidate, EventSource.event_id)
        .join(EventSource, EventSource.candidate_id == DiscoveryCandidate.id)
        .where(EventSource.event_id.in_(event_ids))
    ):
        parts[source_event_id].append(candidate.headline)
        metadata = json.loads(candidate.metadata_json or "{}")
        if metadata.get("summary"):
            parts[source_event_id].append(str(metadata["summary"]))
    return {event_id: unescape("\n".join(values)) for event_id, values in parts.items()}


def relink_stored_news(db: Session, *, apply: bool = False) -> dict[str, object]:
    """Deterministically rebuild company links from already-stored news text."""

    events = list(
        db.scalars(select(Event).where(Event.event_type == "news").order_by(Event.id))
    )
    if not events:
        return {
            "events_scanned": 0,
            "old_links": 0,
            "links_written": 0,
            "linked_events": 0,
            "linked_symbols": 0,
            "unmatched_events": 0,
            "matches_by_method": {},
            "links_by_symbol": {},
            "matched_links": [],
            "applied": apply,
        }

    instruments = list(db.scalars(select(Instrument).order_by(Instrument.symbol)))
    aliases_by_instrument: dict[str, list[str]] = defaultdict(list)
    for instrument_id, alias in db.execute(
        select(InstrumentAlias.instrument_id, InstrumentAlias.alias)
    ):
        aliases_by_instrument[instrument_id].append(alias)

    phrase_candidates: dict[str, list[tuple[str, str, Decimal]]] = defaultdict(list)
    for instrument in instruments:
        for phrase in _name_variants(instrument.name):
            if phrase != _normalized_phrase(instrument.symbol):
                phrase_candidates[phrase].append(
                    (instrument.symbol, "stored_company_name", Decimal("0.980000"))
                )
        for alias in aliases_by_instrument[instrument.id]:
            for phrase in _name_variants(alias):
                if phrase != _normalized_phrase(instrument.symbol):
                    phrase_candidates[phrase].append(
                        (instrument.symbol, "stored_alias", Decimal("0.930000"))
                    )
    unique_phrases = {
        phrase: candidates[0]
        for phrase, candidates in phrase_candidates.items()
        if len({candidate[0] for candidate in candidates}) == 1
    }
    symbols = {instrument.symbol for instrument in instruments}
    stored_text = _stored_news_text(db, events)
    desired: dict[tuple[str, str], tuple[str, Decimal]] = {}
    methods = Counter()
    for event in events:
        raw_text = stored_text[event.id]
        normalized_text = f" {_normalized_phrase(raw_text)} "
        matches: dict[str, tuple[str, Decimal]] = {}
        for phrase, (symbol, method, confidence) in unique_phrases.items():
            if f" {phrase} " in normalized_text:
                matches[symbol] = max(matches.get(symbol, ("", Decimal("0"))), (method, confidence), key=lambda row: row[1])
        for symbol in _explicit_tickers(raw_text) & symbols:
            matches[symbol] = ("stored_ticker", Decimal("0.990000"))
        for symbol in _contextual_tickers(raw_text, symbols):
            matches.setdefault(
                symbol, ("stored_ticker_context", Decimal("0.900000"))
            )
        for symbol, match in matches.items():
            desired[(event.id, symbol)] = match
            methods[match[0]] += 1

    existing_rows = list(
        db.scalars(
            select(EventEntityLink)
            .where(
                EventEntityLink.event_id.in_([event.id for event in events]),
                EventEntityLink.entity_type == "instrument",
            )
            .order_by(EventEntityLink.id)
        )
    )
    if apply:
        retained: set[tuple[str, str]] = set()
        for link in existing_rows:
            key = (link.event_id, link.entity_key.upper())
            if key not in desired or key in retained:
                db.delete(link)
                continue
            method, confidence = desired[key]
            link.entity_key = key[1]
            link.link_method = method
            link.confidence = confidence
            retained.add(key)
        for key, (method, confidence) in desired.items():
            if key not in retained:
                db.add(
                    EventEntityLink(
                        event_id=key[0],
                        entity_type="instrument",
                        entity_key=key[1],
                        link_method=method,
                        confidence=confidence,
                    )
                )
        desired_by_event: dict[str, list[str]] = defaultdict(list)
        for event_id, symbol in desired:
            desired_by_event[event_id].append(symbol)
        for event in events:
            details = json.loads(event.details_json or "{}")
            details["entity_keys"] = sorted(desired_by_event[event.id])
            details["entity_link_version"] = "stored-text-v2"
            event.details_json = json.dumps(details, sort_keys=True)
        db.commit()

    linked_events = {event_id for event_id, _ in desired}
    return {
        "events_scanned": len(events),
        "old_links": len(existing_rows),
        "links_written": len(desired),
        "linked_events": len(linked_events),
        "linked_symbols": len({symbol for _, symbol in desired}),
        "unmatched_events": len(events) - len(linked_events),
        "matches_by_method": dict(sorted(methods.items())),
        "links_by_symbol": dict(sorted(Counter(symbol for _, symbol in desired).items())),
        "matched_links": [
            {
                "event_id": event.id,
                "title": event.title,
                "symbols": sorted(
                    symbol for event_id, symbol in desired if event_id == event.id
                ),
            }
            for event in events
            if any(event_id == event.id for event_id, _ in desired)
        ],
        "applied": apply,
    }
