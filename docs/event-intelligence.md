# Deterministic event intelligence

Phase 6 keeps retained announcements and news as source evidence and creates separate
`normalized_events` records. A normalized event never replaces or mutates its underlying
publication. `normalized_event_evidence` preserves every raw event/source relationship,
while `normalized_event_subjects` records direct issuers separately from derived sectors
and macro factors.

The detector is deterministic-first. Version 2 classifies financial and market events
(earnings, dividends, corporate actions, financing, operational developments/disruptions,
regulation, rates, FX, oil/commodities, and geopolitical risk) as well as useful company
intelligence (governance, insider transactions, corporate calendars, briefings/research,
compliance/Shariah disclosures, and market notices). Numeric/unit patterns may retain an
observed magnitude. MiniLM prototype similarity is only a confidence signal and cannot
publish an event by itself. `unclassified` is reserved for genuinely unresolved evidence.

Materiality rules differ by event type and return `unknown` when their required magnitude
or signal is missing. Confidence records source authority, direct-subject evidence,
corroboration, magnitude, and prototype agreement. Freshness is independent of both.
Phase 6 does not calculate share-price direction, signed company exposure, expected
return, or portfolio-return impact.

Apply the migration and normalize retained evidence from `apps/api`:

```bash
alembic upgrade head
python -m app.jobs.normalize_events --rebuild --confirm-rebuild --all --limit 500
```

The rebuild deletes only reproducible Phase 6 derivatives; raw announcements, news,
documents, citations, and embeddings remain untouched. The command then processes bounded
batches until `scanned` is zero.
New evidence selected by the Celery evidence-index worker is normalized automatically.

Read APIs:

- `GET /research/intelligence-events`
- `GET /companies/{instrument_id}/intelligence-events`
- `GET /portfolios/{portfolio_id}/events`

The global endpoint accepts explicit views: `material` (default), `company_relevant`,
`portfolio_relevant`, `all_classified`, `unresolved`, and `all`. Company intelligence
uses `company_relevant`, so low-materiality governance, calendar, briefing, and compliance
items remain available without flooding the default market-material feed.

Portfolio event responses contain only exact current holding weights for directly named
issuers. Sector association alone never creates a direct company event, and the response
explicitly reports that impact calculations are unavailable without verified sensitivity
inputs.
