"""Read-only company/event projections shared by research, portfolio and Assistant."""

import json
from datetime import UTC, datetime, timedelta, date
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select, func, or_, case
from app.domain.research_relevance import detect_factors, fingerprint, VERSION, utc
from app.models.document import Document, DocumentChunk
from app.models.research_intelligence import (
    CompanyExposureProfile,
    CompanyEventBrief,
    PortfolioEventSnapshot,
)
from app.models.workstation import (
    Event,
    EventSource,
    EventEntityLink,
    NormalizedEvent,
    NormalizedEventEvidence,
    Instrument,
    FinancialFact,
    StandardizedFinancialFact,
    MacroSeries,
    MacroObservation,
)
from app.services.research_evidence_service import report_coverage, company_windows
from app.services.portfolio_service import get_portfolio_summary, get_portfolio_or_404
from app.services.rag_service import active_embedding_model
from app.core.config import settings


def resolve_company(db, symbol):
    row = db.scalar(select(Instrument).where(func.upper(Instrument.symbol) == symbol.upper()))
    if row is None:
        raise HTTPException(404, "Company not found")
    return row


def profile_input(db, instrument):
    return {
        "company": {
            "instrument_id": instrument.id,
            "symbol": instrument.symbol,
            "name": instrument.name,
            "sector": instrument.sector,
        },
        "allowed_factors": ["oil_price", "pk_policy_rate", "usd_pkr"],
        "coverage": report_coverage(db, instrument.symbol),
        "evidence": company_windows(db, instrument.symbol),
    }


def current_profile(db, user, instrument, provider=None, model=None):
    from app.services.research_generation_service import PROFILE_VERSION

    key = fingerprint(profile_input(db, instrument))
    statement = select(CompanyExposureProfile).where(
        CompanyExposureProfile.user_id == user.id,
        CompanyExposureProfile.instrument_id == instrument.id,
        CompanyExposureProfile.input_hash == key,
        CompanyExposureProfile.prompt_version == PROFILE_VERSION,
    )
    if provider:
        statement = statement.where(CompanyExposureProfile.provider == provider)
    if model:
        statement = statement.where(CompanyExposureProfile.model == model)
    return db.scalar(statement.order_by(CompanyExposureProfile.generated_at.desc()).limit(1))


def event_views(db, *, symbol=None, window_days=90, offset=0, limit=5, start=None, end=None):
    """Scope issuers from RAW links. Never inherit the cluster's union of companies.

    Stored normalized classification/materiality/freshness is preserved. Evidence must
    have an indexed, public observed document; failed/pending source references are omitted.
    """
    cutoff = (
        datetime.combine(start, datetime.min.time(), UTC)
        if start
        else datetime.now(UTC) - timedelta(days=window_days)
    )
    query = (
        select(Event, NormalizedEvent)
        .join(NormalizedEventEvidence, NormalizedEventEvidence.raw_event_id == Event.id)
        .join(NormalizedEvent, NormalizedEvent.id == NormalizedEventEvidence.normalized_event_id)
        .where(
            Event.occurred_at >= cutoff,
            Event.occurred_at <= datetime.now(UTC),
            NormalizedEvent.classification_status == "classified",
            NormalizedEvent.materiality.in_(("medium", "high")),
        )
    )
    if end:
        query = query.where(
            Event.occurred_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC)
        )
    if symbol:
        query = query.where(
            Event.id.in_(
                select(EventEntityLink.event_id).where(
                    EventEntityLink.entity_type == "instrument",
                    func.upper(EventEntityLink.entity_key) == symbol.upper(),
                )
            )
        )
    # Evidence selection is applied BEFORE pagination, using EXISTS rather than a multiplying join.
    usable_sources = (
        select(EventSource.event_id)
        .join(Document, Document.id == EventSource.document_id)
        .where(
            EventSource.selection_status.in_(("legacy", "selected", "reference")),
            Document.visibility == "public",
            Document.data_status == "observed",
            Document.status == "parsed",
            Document.id.in_(
                select(DocumentChunk.document_id).where(
                    DocumentChunk.embedding_status == "indexed",
                    DocumentChunk.embedding_model == active_embedding_model(),
                    DocumentChunk.embedding_index_version == settings.embedding_index_version,
                    DocumentChunk.content_type != "boilerplate",
                )
            ),
        )
    )
    query = query.where(Event.id.in_(usable_sources)).order_by(
        case((NormalizedEvent.materiality == "high", 0), else_=1),
        Event.occurred_at.desc(),
        Event.id,
    )
    rows = list(db.execute(query.offset(offset).limit(limit)))
    if not rows:
        return []
    ids = [raw.id for raw, _norm in rows]
    sources = list(
        db.scalars(
            select(EventSource)
            .join(Document, Document.id == EventSource.document_id)
            .where(
                EventSource.event_id.in_(ids),
                EventSource.selection_status.in_(("legacy", "selected", "reference")),
                Document.visibility == "public",
                Document.data_status == "observed",
                Document.status == "parsed",
            )
        )
    )
    links = list(
        db.scalars(
            select(EventEntityLink).where(
                EventEntityLink.event_id.in_(ids), EventEntityLink.entity_type == "instrument"
            )
        )
    )
    document_ids = {s.document_id for s in sources}
    documents = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_(document_ids)))}
    # Rank in SQL so a large market feed does not load all announcement bodies.
    ranked_chunks = (
        select(
            DocumentChunk.id.label("id"),
            func.row_number()
            .over(partition_by=DocumentChunk.document_id, order_by=DocumentChunk.chunk_index)
            .label("rank"),
        )
        .where(
            DocumentChunk.document_id.in_(document_ids),
            DocumentChunk.embedding_status == "indexed",
            DocumentChunk.embedding_model == active_embedding_model(),
            DocumentChunk.embedding_index_version == settings.embedding_index_version,
            DocumentChunk.content_type != "boilerplate",
        )
        .subquery()
    )
    chunks_by_document = {}
    for chunk in db.scalars(
        select(DocumentChunk)
        .join(ranked_chunks, ranked_chunks.c.id == DocumentChunk.id)
        .where(ranked_chunks.c.rank <= 2)
    ):
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk)
    sources_by_event, links_by_event = {}, {}
    for source in sources:
        sources_by_event.setdefault(source.event_id, []).append(source)
    for link in links:
        links_by_event.setdefault(link.event_id, []).append(link)
    result = []
    for raw, norm in rows:
        selected = sources_by_event.get(raw.id, [])
        evidence = []
        for source in sorted(selected, key=lambda item: item.id):
            document = documents[source.document_id]
            chunks = chunks_by_document.get(source.document_id, [])
            for chunk in sorted(chunks, key=lambda item: item.chunk_index):
                evidence.append(
                    {
                        "id": "chunk:" + chunk.id,
                        "raw_event_id": raw.id,
                        "document_id": document.id,
                        "title": document.title,
                        "source_name": source.source_name,
                        "source_url": source.source_url,
                        "published_at": source.published_at,
                        "page_number": chunk.page_number,
                        "text": " ".join(chunk.chunk_text.split())[:1000],
                    }
                )
        issuer_links = links_by_event.get(raw.id, [])
        text = raw.title + " " + " ".join(e["text"] for e in evidence)
        result.append(
            {
                "id": raw.id,
                "event_key": "raw:" + raw.id,
                "raw_event_id": raw.id,
                "normalized_event_id": norm.id,
                "title": raw.title,
                "occurred_at": raw.occurred_at,
                "event_type": norm.event_type,
                "classification_status": norm.classification_status,
                "source_document_type": "announcement"
                if raw.event_type == "announcement"
                else "news",
                "factor": norm.factor,
                "factors": detect_factors(text),
                "materiality": norm.materiality,
                "confidence": norm.confidence,
                "freshness_status": norm.freshness_status,
                "freshness_score": norm.freshness_score,
                "detection_version": norm.detection_version,
                "subjects": [
                    {
                        "subject_type": "instrument",
                        "subject_key": link.entity_key.upper(),
                        "link_method": link.link_method,
                        "confidence": link.confidence,
                        "is_direct": True,
                    }
                    for link in sorted(issuer_links, key=lambda item: item.entity_key)
                ],
                "evidence": evidence,
                "impact": {"status": "not_calculated", "direction": None, "expected_return": None},
            }
        )
    # News may share a view only when every raw member is visible here and its
    # issuer/factor scope agrees. Announcements always retain issuer/raw identity.
    cluster_sizes = dict(
        db.execute(
            select(
                NormalizedEventEvidence.normalized_event_id,
                func.count(),
            )
            .where(
                NormalizedEventEvidence.normalized_event_id.in_(
                    {r["normalized_event_id"] for r in result}
                )
            )
            .group_by(NormalizedEventEvidence.normalized_event_id)
        ).all()
    )
    groups = {}
    for row in result:
        groups.setdefault(row["normalized_event_id"], []).append(row)
    merged, consumed = [], set()
    for row in result:
        cluster = groups[row["normalized_event_id"]]

        def signature(r):
            return (
                tuple(sorted(s["subject_key"] for s in r["subjects"])),
                tuple(sorted(r["factors"])),
            )

        compatible = (
            len(cluster) > 1
            and len(cluster) == cluster_sizes[row["normalized_event_id"]]
            and all(
                r["source_document_type"] == "news" and signature(r) == signature(row)
                for r in cluster
            )
        )
        if compatible:
            if row["normalized_event_id"] in consumed:
                continue
            consumed.add(row["normalized_event_id"])
            row = dict(row)
            row["event_key"] = "normalized:" + row["normalized_event_id"]
            row["raw_event_ids"] = sorted(r["raw_event_id"] for r in cluster)
            evidence = {e["id"]: e for r in cluster for e in r["evidence"]}
            row["evidence"] = [evidence[key] for key in sorted(evidence)]
        merged.append(row)
    return merged


def company_events(db, user, instrument, *, limit=5, window_days=90, candidate_events=None):
    direct = event_views(db, symbol=instrument.symbol, window_days=window_days, limit=limit)
    for row in direct:
        row["relationship_kind"] = "direct"
    profile = current_profile(db, user, instrument) if user else None
    relationships = json.loads(profile.relationships_json) if profile else []
    factors = {r["factor"] for r in relationships}
    indirect = []
    if factors:
        # Scan only selected evidence candidates, never infer from the broad macro tag.
        for candidate in (
            candidate_events
            if candidate_events is not None
            else event_views(db, window_days=window_days, limit=1000)
        ):
            row = dict(candidate)
            matched = factors.intersection(row["factors"])
            if matched and instrument.symbol.upper() not in {
                s["subject_key"] for s in row["subjects"]
            }:
                row["relationship_kind"] = "ai_proposed_indirect"
                row["relationships"] = [r for r in relationships if r["factor"] in matched]
                indirect.append(row)
    # Digest admission: up to three direct and two indirect, then fill remaining slots.
    chosen = direct[: min(3, limit)] + indirect[: min(2, max(0, limit - 3))]
    seen = {r["event_key"] for r in chosen}
    chosen += [r for r in direct[3:] + indirect[2:] if r["event_key"] not in seen][
        : max(0, limit - len(chosen))
    ]
    chosen.sort(
        key=lambda r: (
            -int(r["materiality"] == "high"),
            -utc(r["occurred_at"]).timestamp(),
            r["event_key"],
        )
    )
    return chosen[:limit]


def exact_facts(db, instrument, limit=12):
    today = date.today()
    filing = list(
        db.scalars(
            select(FinancialFact)
            .where(
                FinancialFact.instrument_id == instrument.id,
                FinancialFact.period_end <= today,
                or_(FinancialFact.filing_date.is_(None), FinancialFact.filing_date <= today),
            )
            .order_by(
                FinancialFact.period_end.desc(), FinancialFact.version.desc(), FinancialFact.id
            )
            .limit(limit)
        )
    )
    values = [
        {
            "id": "fact:" + f.id,
            "metric": f.taxonomy_key,
            "value": str(f.value),
            "unit": f.unit,
            "currency": f.currency,
            "period_end": str(f.period_end),
            "document_id": f.document_id,
            "page_number": f.page_number,
        }
        for f in filing
    ]
    if len(values) < limit:
        secondary = db.scalars(
            select(StandardizedFinancialFact)
            .where(
                StandardizedFinancialFact.instrument_id == instrument.id,
                StandardizedFinancialFact.quality_status == "observed",
                StandardizedFinancialFact.period_end <= today,
            )
            .order_by(StandardizedFinancialFact.period_end.desc(), StandardizedFinancialFact.id)
            .limit(limit - len(values))
        )
        values += [
            {
                "id": "standardized:" + f.id,
                "metric": f.metric,
                "value": str(f.value),
                "unit": f.unit,
                "currency": f.currency,
                "period_end": str(f.period_end),
                "source_url": f.source_url,
            }
            for f in secondary
        ]
    return values


def digest_input(db, user, instrument, events=None):
    events = events if events is not None else company_events(db, user, instrument)
    profile = current_profile(db, user, instrument)
    macro = []
    for factor, aliases in {
        "oil_price": ("BRENT_USD_BBL", "GLOBAL_CRUDE_OIL_USD_BBL"),
        "pk_policy_rate": ("PK_POLICY_RATE",),
        "usd_pkr": ("PK_USD_PKR",),
    }.items():
        series = next(
            (
                db.scalar(select(MacroSeries).where(MacroSeries.key == alias))
                for alias in aliases
                if db.scalar(select(MacroSeries.id).where(MacroSeries.key == alias))
            ),
            None,
        )
        if not series:
            continue
        obs = db.scalar(
            select(MacroObservation)
            .where(
                MacroObservation.series_id == series.id,
                MacroObservation.is_selected.is_(True),
                MacroObservation.effective_date <= date.today(),
            )
            .order_by(MacroObservation.effective_date.desc())
            .limit(1)
        )
        if obs:
            macro.append(
                {
                    "id": "macro:" + obs.id,
                    "factor": factor,
                    "value": str(obs.value),
                    "unit": series.unit,
                    "effective_date": str(obs.effective_date),
                    "artifact_id": obs.artifact_id,
                }
            )
    return {
        "company": {
            "instrument_id": instrument.id,
            "symbol": instrument.symbol,
            "name": instrument.name,
            "sector": instrument.sector,
        },
        "facts": exact_facts(db, instrument),
        "macro": macro,
        "relationships": json.loads(profile.relationships_json) if profile else [],
        "company_evidence": company_windows(db, instrument.symbol, 6),
        "relationship_evidence": [
            e
            for e in json.loads(profile.evidence_json)
            if e["id"]
            in {ref for r in json.loads(profile.relationships_json) for ref in r["evidence_ids"]}
            and e["id"] not in {c["id"] for c in company_windows(db, instrument.symbol, 6)}
        ]
        if profile
        else [],
        "events": [{k: v for k, v in event.items() if k != "saved_brief"} for event in events],
    }


def attach_briefs(db, user, instrument, events):
    from app.services.research_generation_service import cached_event_keys

    if not events:
        return events
    by_key = cached_event_keys(db, user, instrument, digest_input(db, user, instrument, events))
    for e in events:
        b = by_key.get(e["event_key"])
        e["saved_brief"] = (
            {
                "explanation": json.loads(b.brief_json),
                "generated_at": b.generated_at,
                "evidence": json.loads(b.evidence_json),
            }
            if b
            else None
        )
    return events


def company_intelligence(db, user, symbol):
    instrument = resolve_company(db, symbol)
    profile = current_profile(db, user, instrument)
    return {
        "instrument_id": instrument.id,
        "symbol": instrument.symbol,
        "events": attach_briefs(db, user, instrument, company_events(db, user, instrument)),
        "profile": {
            "relationships": json.loads(profile.relationships_json),
            "coverage_gaps": json.loads(profile.coverage_json),
            "generated_at": profile.generated_at,
            "evidence": json.loads(profile.evidence_json),
        }
        if profile
        else None,
        "reports": report_coverage(db, instrument.symbol),
        "generation": "manual",
    }


def portfolio_intelligence(db, user, portfolio_id, limit=5):
    portfolio = get_portfolio_or_404(db, user, portfolio_id)
    summary = get_portfolio_summary(db, user, portfolio_id)
    candidates = event_views(db, limit=1000)
    instruments = {h.symbol: resolve_company(db, h.symbol) for h in summary.holdings}
    profiles = {
        symbol: current_profile(db, user, instrument) for symbol, instrument in instruments.items()
    }
    briefs = list(
        db.execute(
            select(
                CompanyEventBrief.instrument_id,
                CompanyEventBrief.event_key,
                CompanyEventBrief.input_hash,
                CompanyEventBrief.prompt_version,
                CompanyEventBrief.provider,
                CompanyEventBrief.model,
                CompanyEventBrief.generated_at,
            ).where(
                CompanyEventBrief.user_id == user.id,
                CompanyEventBrief.instrument_id.in_([i.id for i in instruments.values()]),
            )
        )
    )
    macro = list(
        db.execute(
            select(
                MacroSeries.key,
                MacroObservation.id,
                MacroObservation.value,
                MacroObservation.effective_date,
                MacroObservation.artifact_id,
            )
            .join(MacroObservation, MacroObservation.series_id == MacroSeries.id)
            .where(
                MacroSeries.key.in_(
                    ("BRENT_USD_BBL", "GLOBAL_CRUDE_OIL_USD_BBL", "PK_POLICY_RATE", "PK_USD_PKR")
                ),
                MacroObservation.is_selected.is_(True),
                MacroObservation.effective_date <= date.today(),
            )
            .order_by(MacroSeries.key, MacroObservation.effective_date, MacroObservation.id)
        )
    )
    dependencies = fingerprint(
        {
            "version": VERSION,
            "window_date": str(date.today()),
            "summary": summary.model_dump(mode="json"),
            "candidates": candidates,
            "profiles": {
                symbol: {
                    "input": profile_input(db, instruments[symbol]),
                    "id": profile.id if profile else None,
                }
                for symbol, profile in profiles.items()
            },
            "briefs": [list(row) for row in briefs],
            "macro": [list(row) for row in macro],
            "facts": {
                symbol: exact_facts(db, instrument) for symbol, instrument in instruments.items()
            },
        }
    )
    snapshot = db.scalar(
        select(PortfolioEventSnapshot)
        .where(
            PortfolioEventSnapshot.user_id == user.id,
            PortfolioEventSnapshot.portfolio_id == portfolio_id,
            PortfolioEventSnapshot.input_hash == dependencies,
            PortfolioEventSnapshot.calculation_version == VERSION,
        )
        .order_by(PortfolioEventSnapshot.generated_at.desc())
        .limit(1)
    )
    if snapshot:
        cached = json.loads(snapshot.payload_json)
        cached["events"] = cached["events"][:limit]
        return cached
    priced = all(h.latest_price is not None for h in summary.holdings)
    valid = priced and summary.valuation_complete and summary.total_value > 0
    grouped = {}
    for holding in summary.holdings:
        instrument = resolve_company(db, holding.symbol)
        events = attach_briefs(
            db, user, instrument, company_events(db, user, instrument, candidate_events=candidates)
        )
        for event in events:
            entry = grouped.setdefault(
                event["event_key"],
                {
                    "event": {
                        k: v
                        for k, v in event.items()
                        if k not in {"saved_brief", "relationships", "relationship_kind"}
                    },
                    "companies": {},
                },
            )
            entry["companies"][holding.symbol] = {
                "symbol": holding.symbol,
                "relationship_kind": event["relationship_kind"],
                "saved_brief": event["saved_brief"],
                "current_portfolio_weight": str(holding.market_value / summary.total_value)
                if valid
                else None,
            }
    rows = []
    for entry in grouped.values():
        companies = list(entry["companies"].values())
        weight = sum(Decimal(c["current_portfolio_weight"]) for c in companies) if valid else None
        rows.append(
            {
                "event": entry["event"],
                "companies": companies,
                "potentially_affected_weight": str(weight) if weight is not None else None,
                "impact_direction": None,
                "impact_calculation": "not_calculated",
            }
        )
    rows.sort(
        key=lambda e: (
            -int(e["event"]["materiality"] == "high"),
            -Decimal(e["potentially_affected_weight"] or "0"),
            -utc(e["event"]["occurred_at"]).timestamp(),
        )
    )
    payload = {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.name,
        "events": rows[:limit],
        "valuation_complete": valid,
        "total_value": str(summary.total_value),
        "coverage": {
            "holdings": len(summary.holdings),
            "priced_holdings": sum(h.latest_price is not None for h in summary.holdings),
        },
        "calculation_version": VERSION,
    }
    payload["input_hash"] = dependencies
    return payload


def persist_snapshot(db, user, portfolio_id):
    payload = portfolio_intelligence(db, user, portfolio_id, limit=20)
    existing = db.scalar(
        select(PortfolioEventSnapshot).where(
            PortfolioEventSnapshot.portfolio_id == portfolio_id,
            PortfolioEventSnapshot.user_id == user.id,
            PortfolioEventSnapshot.input_hash == payload["input_hash"],
            PortfolioEventSnapshot.calculation_version == VERSION,
        )
    )
    if not existing:
        db.add(
            PortfolioEventSnapshot(
                user_id=user.id,
                portfolio_id=portfolio_id,
                input_hash=payload["input_hash"],
                calculation_version=VERSION,
                valuation_as_of=datetime.now(UTC).isoformat(),
                payload_json=json.dumps(payload, default=str),
            )
        )
        db.commit()
