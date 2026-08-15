# Global Evidence Pass 3

Pass 3 adds conservative historical hydration only. It does not add sources,
publisher parsers, Playwright, live-browser validation, retrieval changes, entity
intelligence, or assistant reasoning.

## Presets

| Preset | Default range | Sources | Candidate/fetch/storage ceilings |
| --- | --- | --- | --- |
| `psx_12m` | trailing 365 days | existing PSX announcements adapter | 5,000 / 5,000 / 512 MiB |
| `deep_company_12m` | trailing 365 days | existing PSX + GDELT adapters | 100 / 100 / 250 MiB per deep instrument |
| `news_90d` | trailing 90 days | existing GDELT adapter and configured Phase 3 topics | 200 / 200 / 250 MiB |

These are hard request ceilings, not ingestion targets. Metadata relevance,
deduplication, story selection, and selected-evidence storage rules still apply.
The API and CLI may lower any ceiling. Raising a preset ceiling is rejected until
every selected source has accumulated seven continuous healthy production days.
A discovery failure resets that source's health interval.

## Execution and recovery

Each `historical_hydrate` task performs at most one discovery page of at most
`EVIDENCE_HISTORICAL_BATCH_CANDIDATES` candidates. Its unit index, PSX offset,
date range, source scope, counters, and halt/yield reason are stored on the
Postgres `evidence_refresh_requests` row. The scheduler can therefore resume a
stopped job without Redis state or restarting its completed pages.

Historical requests and candidates use priority `8`; live work uses priority
`0`. The scheduler does not publish a historical slice while durable live work
meets `EVIDENCE_HISTORICAL_LIVE_BACKLOG_RESERVE` (one item by default). Worker
prefetch remains one. Candidate, fetch, and byte ceilings are enforced again at
the worker boundary so restarts or duplicate delivery cannot bypass them.

Progress is available through:

- `GET /ingestion/evidence/requests` for ownership-scoped request progress;
- `GET /ingestion/evidence/operations` for historical request counts and byte totals;
- the request's `progress.halted_reason`, which reports live yielding or a reached budget.

## Creating the conservative bootstrap

Apply migrations, start the existing Phase 3 workers/scheduler, and create the
three durable presets:

```bash
docker compose run --rm worker-evidence-discovery alembic upgrade head
docker compose up -d postgres redis worker-evidence-discovery worker-evidence-fetch \
  worker-evidence-parse worker-evidence-pdf worker-evidence-index \
  worker-historical-hydrate evidence-scheduler
docker compose run --rm worker-evidence-discovery \
  python -m app.jobs.evidence_history --preset all
```

`--preset all` creates one PSX request, one 90-day news request, and one request
for every instrument currently considered Deep by the existing Phase 2 rules.
Creation is idempotent for the same owner, scope, preset, and date range.

For one explicitly selected deep company:

```bash
docker compose run --rm worker-evidence-discovery \
  python -m app.jobs.evidence_history --preset deep_company_12m --symbol HBL
```

The authenticated `POST /ingestion/evidence/historical` API accepts the same
presets, optional date bounds, a permitted source subset, and lower/health-gated
higher budgets.

## Seven-day expansion checkpoint

Do not increase range or source breadth during the initial Pass 3 bootstrap. After
seven healthy days, operators may raise the news range up to the hard 12-month cap
and increase candidate/fetch/storage ceilings for the existing preset sources.
Source breadth, additional publishers, Playwright, and publisher-specific parser
work belong to Pass 4.
