# Global Evidence Pass 4: official-source canary

This pass adds Pakistan and global official sources through the existing generic
RSS/Atom and HTML-listing adapters. Tier-1 publishers, specialist sector feeds,
publisher-specific parsers, Playwright, and browser validation are intentionally
excluded from this round.

## Controlled information funnel

The worker path records and reports:

```text
discovered
→ relevant
→ successfully extracted
→ non-duplicate
→ unique story
→ selected as best evidence
```

Duplicate rate never disables a source by itself. After at least 100 fetches, a
source is flagged `review_low_yield` only when both its unique-story rate and its
evidence-selection rate are below 1%. This is an operator review signal, not an
automatic shutdown. An official source can remain valuable even when it mostly
confirms existing stories.

## Sources in this round

Pakistan official:

- Ministry of Finance, PBS, SECP, NEPRA, OGRA, and NCCPL;
- existing PSX and SBP adapters remain active independently of this canary.

Global official:

- World Bank, Federal Reserve, ECB, BIS, EIA, OPEC, and U.S. Treasury OFAC;
- the existing IMF adapter remains active independently of this canary.

The SEC EDGAR generic feed contract and fixture are registered, but its data
source stays disabled: fetching the unfiltered current-filings firehose would
waste the canary budget. Enable it only after selected issuer CIKs are explicitly
allowlisted; that scoped work remains within the global-official category.

Each new source declares its discovery URL, generic adapter kind, link filter,
topic, provenance, per-source budgets, and a documented non-browser fallback in
`app/ingestion/evidence_catalog.py`. Fixture tests exercise every source through
the same generic adapters. Adding another compatible source is a `SourceSpec`
entry plus a fixture; it does not require a new provider class.

| Source | Adapter | Discover/day | Fetch/day | Select/day | Raw/day |
| --- | --- | ---: | ---: | ---: | ---: |
| Pakistan Ministry of Finance | listing | 50 | 20 | 8 | 100 MiB |
| Pakistan Bureau of Statistics | listing | 50 | 20 | 8 | 150 MiB |
| SECP | listing | 75 | 25 | 10 | 200 MiB |
| NEPRA | listing | 40 | 15 | 6 | 100 MiB |
| OGRA | listing | 40 | 15 | 6 | 100 MiB |
| NCCPL | listing | dormant | dormant | dormant | dormant |
| World Bank | listing | 50 | 15 | 6 | 100 MiB |
| Federal Reserve | RSS | 50 | 15 | 6 | 75 MiB |
| ECB | RSS | 50 | 15 | 6 | 75 MiB |
| BIS | RSS | 40 | 12 | 5 | 75 MiB |
| EIA | RSS | 40 | 12 | 5 | 75 MiB |
| OPEC | listing | 40 | 12 | 5 | 75 MiB |
| OFAC | listing | 50 | 15 | 6 | 75 MiB |
| SEC EDGAR | RSS | dormant | dormant | dormant | dormant |

NCCPL returned a verified HTTP 403 to the bounded client, so its generic contract
remains registered but the data source is dormant. The fallback is manual import;
the application does not attempt an anti-bot bypass.

## Hard seven-day canary limits

The defaults are ceilings, not targets:

| Boundary | Global ceiling |
| --- | ---: |
| metadata discoveries | 2,000/day |
| full HTTP fetch attempts | 250/day |
| newly selected evidence | 75/day |
| downloaded raw bytes | 1.5 GiB/day |
| downloaded raw bytes | 10 GiB/trailing seven days |
| concurrently reserved fetch work | 120 |
| HTML/article response | 5 MiB |
| PDF response | 25 MiB |

Every source also has a smaller daily discovery, fetch, selection, and storage
ceiling. The effective allowance is the lower of its source ceiling and the
global ceiling. Postgres advisory transaction locks serialize reservations
across Celery processes. A reached budget defers work to the next UTC day; it is
not misclassified as irrelevant evidence and does not consume retry attempts.
Live candidates continue to outrank historical candidates.

The user's 10,000–15,000 discovery / 1,500–2,000 fetch envelope applies to the
eventual full Pass 4 mix. This official-only subset is intentionally smaller:
its enabled per-source ceilings sum to 575 discoveries, 191 fetches, 77 selections,
and 1,200 MiB per day. The global 75-selection ceiling is lower, so the absolute
seven-day maxima are 4,025 discoveries, 1,337 fetches, 525 selections, and under
8.3 GiB. Actual retained counts should be materially lower after relevance and
deduplication.

Official historical expansion is deliberately not started by this pass. The
first seven days validate current discovery, extraction, deduplication,
clustering, selection, and source health. Only after seven continuous healthy
production days should a separate bounded historical request be added (roughly
500–1,000 candidates for Pakistan official sources and 500–1,000 for global
official sources). A generic listing cannot claim twelve-month coverage unless
the official archive exposes those dates, so archive pagination must be verified
before enabling such a preset.

## Local `.venv` rollout

Use Postgres and Redis services already running locally. Do not rebuild a Docker
image. From `apps/api`:

```bash
source .venv/bin/activate
alembic upgrade head
```

Celery imports the source registry when each worker starts. After deploying this
pass or changing the catalog, stop and restart every evidence worker; restarting
only the scheduler leaves old workers unable to resolve newly added source keys.

Set these in `apps/api/.env` (use a real monitored contact address because SEC
expects an identifiable user agent):

```dotenv
EVIDENCE_ENABLED=true
EVIDENCE_PASS4_OFFICIAL_ENABLED=true
EVIDENCE_CONTACT_EMAIL=your-monitored-address@example.com
```

Run the existing concurrent pools in separate terminals:

```bash
celery -A app.celery_app worker -n discovery@%h -Q evidence_discovery --concurrency=4 --loglevel=INFO
celery -A app.celery_app worker -n fetch@%h -Q evidence_fetch --concurrency=16 --loglevel=INFO
celery -A app.celery_app worker -n parse@%h -Q evidence_parse --concurrency=6 --loglevel=INFO
celery -A app.celery_app worker -n pdf@%h -Q evidence_pdf --concurrency=2 --loglevel=INFO
celery -A app.celery_app worker -n index@%h -Q evidence_index --concurrency=4 --loglevel=INFO
celery -A app.celery_app worker -n historical@%h -Q historical_hydrate --concurrency=2 --loglevel=INFO
python -m app.jobs.evidence_scheduler
```

On macOS with Python 3.13, use Celery's threads pool if the prefork pool repeats
`SIGSEGV` crashes:

```bash
celery -A app.celery_app worker -P threads -Q evidence_fetch --concurrency=16 --loglevel=INFO
```

The implementation smoke is fixture-only and performs no corpus ingestion:

```bash
pytest -q app/tests/test_evidence_pass4_official.py
```

After the workers start, one scheduler cycle initializes source rows and queues
only bounded due work:

```bash
python -m app.jobs.evidence_scheduler --once
python -m app.jobs.evidence_status --watch 10
```

The status command reports Redis queue depths plus the Postgres source funnel,
budgets, provenance, fallbacks, errors, and health timestamps. Do not create an
official 12-month historical preset during the first seven-day canary.
