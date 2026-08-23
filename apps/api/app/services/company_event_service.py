import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import DocumentChunk
from app.models.workstation import Event, EventEntityLink, EventSource, Instrument, InstrumentAlias


@dataclass(frozen=True)
class SourcedCompanyEvent:
    event: Event
    sources: tuple[EventSource, ...]


CORPORATE_SUFFIX = re.compile(
    r"\s+(?:limited|ltd\.?|plc|modaraba|reit)\s*$",
    flags=re.IGNORECASE,
)


def contains_explicit_instrument_reference(
    text: str,
    symbol: str,
    names: tuple[str, ...],
) -> bool:
    """Require issuer identity or explicit ticker notation, not a bare word/acronym."""

    normalized_symbol = symbol.strip().upper()
    ticker_markers = (
        rf"\${re.escape(normalized_symbol)}(?![A-Za-z0-9])",
        rf"\bPSX\s*:\s*{re.escape(normalized_symbol)}\b",
        rf"\b{re.escape(normalized_symbol)}\.PSX\b",
        rf"\({re.escape(normalized_symbol)}\s*:\s*PSX\)",
    )
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in ticker_markers):
        return True

    normalized = text.casefold()
    for name in names:
        candidate = (name or "").strip()
        variants = {candidate, CORPORATE_SUFFIX.sub("", candidate).strip()}
        for variant in variants:
            if len(variant) < 4 or variant.upper() == normalized_symbol:
                continue
            if re.search(rf"(?<!\w){re.escape(variant.casefold())}(?!\w)", normalized):
                return True
    return False


def sourced_company_events(db: Session, instrument: Instrument) -> list[SourcedCompanyEvent]:
    """Return observed company events, validating legacy news links from stored text only."""

    event_ids = list(
        dict.fromkeys(
            db.scalars(
                select(EventEntityLink.event_id).where(
                    EventEntityLink.entity_type == "instrument",
                    func.upper(EventEntityLink.entity_key) == instrument.symbol.upper(),
                )
            )
        )
    )
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
        if event.event_type == "news" and not contains_explicit_instrument_reference(
            text_by_event[event.id], instrument.symbol, (instrument.name, *aliases)
        ):
            continue
        result.append(SourcedCompanyEvent(event=event, sources=sources))
    return result
