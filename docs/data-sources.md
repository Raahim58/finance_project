# Data Sources

The production architecture is current-data oriented. `mock` is development-only. A provider is enabled only after this sequence succeeds:

```text
inspect the live source
  -> record the actual request/response contract
  -> capture a bounded fixture plus original hash/metadata
  -> implement semantic validation and parsing
  -> pass offline fixture tests
  -> enable the adapter
```

No endpoint, form field, selector, download URL, unit, or date convention may be guessed. Raw responses are retained when the adapter exposes them. Adapters that currently return parsed rows instead create an explicitly labeled `normalized_provider_output` artifact; this is never described as raw. The database records source URL, SHA-256, parser version, content type, effective time, and storage path.

## Provider status

| Source | Status | Observed contract and precedence |
|---|---|---|
| PSX DPS | Integrated + scheduled, primary prices | The observed ordinary-equity symbol feed defines the active universe. Current and monthly historical OHLCV are validated, reconciled, selected by priority, and retained with provenance. Company-page financial tables are separate `standardized_secondary` screening inputs. Invalid rows become quality issues. |
| DPS symbol-price ZIP | Disabled | Its URL was discovered from the live manifest, but ordinary direct and cookie/referer requests returned HTTP 403. No bypass is attempted. |
| PSX Financials | Celery historical + incremental | Catalogue coverage is separate from PDF/extraction coverage. Existing PDFs do not consume historical budgets. Text-native statement pages use positional extraction. Sparse/image-only reports use bounded Poppler rendering plus Tesseract OCR; only known rows with an explicit reporting scale are promoted, with lower OCR confidence and provenance. |
| SCSTrade | Integrated + weekly supplemental schedule | Verified JSON history is normalized into canonical observations at lower priority than DPS. |
| SBP key indicators | Integrated + daily schedule | Raw official page HTML is retained. Policy rate and observed 3-month MTB cut-off yield are effective-dated; the latter is explicitly marked risk-free. Broader EasyData FX/reserve/monetary history still needs stable dataset contracts. |
| PBS Price Statistics | Integrated + weekly schedule | The current parser covers the official monthly SPI item workbook. Broader CPI/release/revision coverage remains incomplete. |
| World Bank Pink Sheet | Integrated + monthly schedule | Monthly commodity workbook rows are persisted with artifact provenance. |
| Canonical macro pipeline | Dedicated Celery queue + scheduler | Twenty-six source-independent series use ordered provider ladders across World Bank, FRED, ECB, SBP, IMF-contract, EIA-contract, and official workbooks. Conflicts are retained and reconciled; see [Canonical Macro Ingestion](macro-ingestion.md). |
| Mettis Global | Integrated + daily legacy metadata schedule | Headline, canonical URL, timestamp, author, and visible summary become sourced events/documents. The Pass 2 evidence scheduler keeps its separate Mettis adapter disabled by default to prevent duplicate polling while this legacy schedule remains active. |
| Yahoo/yfinance | Degraded fallback | Unofficial `.KA` fallback only. The latest live verification hit an explicit rate limit; it must never silently outrank DPS. |
| NCCPL | Manual import only | Ordinary access returned Cloudflare HTTP 403. No browser automation or anti-bot bypass is used. |
| Phase 3 PSX announcements | Pass 2 scheduled evidence source | Uses the observed `POST /announcements` form/table contract. Symbol, company, category, timestamp, attachment URL/type, and stable announcement ID are normalized. Only high-value attachment categories enter the bounded PDF queue. |
| Dawn / Business Recorder | Pass 2 scheduled evidence sources | Their current public RSS feeds use the generic RSS/Atom adapter. Discovery metadata passes a cheap relevance gate before article retrieval. |
| SBP releases | Pass 2 scheduled evidence source | Official media-center release links use the generic bounded listing adapter. Existing structured SBP observations remain separate and authoritative for exact rates and values. |
| IMF news | Pass 2 scheduled evidence source | Official News release/article links use bounded listing discovery because a stable working official feed contract has not been fixture-verified. This does not reclassify narrative releases as structured macro facts. |
| GDELT DOC 2 | Pass 2 scheduled discovery source | Free broad discovery safety net using bounded configured queries and JSON article lists. Publisher pages remain the evidence source; GDELT is discovery metadata, not an authority for article facts. |
| Generic sitemap / news sitemap | Pass 1 adapter available | Namespace-safe XML parsing supports ordinary and Google News sitemaps. A source is enabled only after its concrete sitemap URL is verified and fixture-tested. |
| `psxdata` | Compatibility/comparison only | It wraps DPS and is not canonical. Retire after direct DPS parity is complete. |
| Vendor | Disabled placeholder | Requires an explicit verified contract and credentials. |

Fixture sidecars live under `apps/api/app/tests/fixtures/providers/`. They record URLs, methods, non-secret request fields, retrieval timestamps, original hashes, truncation status, parser versions, and use notes.

## Runtime settings

```bash
MARKET_DATA_MODE=auto
MARKET_DATA_REFRESH_SECONDS=300
MARKET_HISTORY_YEARS=5
MARKET_HISTORY_BOOTSTRAP_ENABLED=true
SCHEDULED_RESEARCH_ENABLED=true
SOURCE_ARTIFACT_ROOT=./data/artifacts
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
MACRO_INGESTION_ENABLED=true
MACRO_QUEUE_TARGET=8
FRED_API_KEY=
```

`auto` tries verified DPS first and uses Yahoo only as a labeled fallback. Exact prices, rankings, freshness, and sector statistics come from database queries. Mock observations are eligible only when `MARKET_DATA_MODE=mock`; local `APP_ENV` does not make data synthetic. No live index value is synthesized from constituent averages.

## Commands

```bash
cd apps/api
python -m app.jobs.scheduler --once
python -m app.jobs.scheduler
celery -A app.celery_app worker -Q broad_fundamentals --concurrency=20
celery -A app.celery_app worker -Q dps_history --concurrency=24
celery -A app.celery_app worker -Q financial_download --concurrency=12
celery -A app.celery_app worker -Q financial_extract --concurrency=3
celery -A app.celery_app worker -P threads -n macro@%h -Q macro --concurrency=4 --loglevel=INFO
MACRO_INGESTION_ENABLED=true python -u -m app.jobs.macro_scheduler
python -m app.jobs.macro_status
```

Pass 1 evidence smoke runs are synchronous and bounded:

```bash
cd apps/api
alembic upgrade head
python -m app.jobs.evidence_pass1 --source psx_announcements --limit 10
python -m app.jobs.evidence_pass1 --source dawn --limit 10
python -m app.jobs.evidence_pass1 --source gdelt --limit 25
```

Available Pass 1 keys are `psx_announcements`, `dawn`, `business_recorder`,
`mettis`, `sbp_releases`, `imf_news`, and `gdelt`. These commands do not start a
scheduler and do not modify Phase 2 queue production.

Rebuild company links from already-stored news without discovery or network access:

```bash
cd apps/api
python -m app.jobs.relink_stored_news          # dry-run audit
python -m app.jobs.relink_stored_news --apply  # replace legacy news links
```

The relinker uses only retained event/candidate headlines and summaries, canonical
company names, unambiguous aliases, explicit ticker notation, and case-sensitive
tickers with Pakistan-market context. It removes links that cannot be reproduced
from that stored evidence and leaves the underlying news events untouched.

Hybrid demo/live initialization:

```bash
DEMO_USER_PASSWORD='choose-a-local-password' python -m app.seed.demo
MARKET_DATA_MODE=auto python -m app.jobs.scheduler --once
```

`ENGRO` is retained as its own historical/delisted identity and is never mapped
to a fresh quote from another security. Existing portfolios holding `ENGRO` therefore
show an unavailable/stale current valuation until an explicit corporate-action
workflow migrates that investor-owned position; the application does not silently
rewrite it.

Manual portfolio entry remains the broker fallback. Never use password scraping or password-based broker automation.

## Health and completeness

Every scheduled provider runs independently. A DPS/market-price failure prevents only its dependent history bootstrap; it does not skip Mettis, PSX Financials, SBP, PBS, World Bank, or SCSTrade. Each provider attempt records a terminal `success`, `partial`, `failed`, or `skipped`-compatible state, counts, an error summary, diagnostics, and the latest resulting observation time when applicable.

Authenticated operational endpoints:

- `GET /ingestion/health` returns source status, last attempt/success, latest observed data, provider-specific freshness SLA, counts, and errors.
- `GET /ingestion/companies/{symbol}/completeness` returns observed-live coverage for prices, fundamentals, reports, announcements, and news. Mock/demo rows do not count.

Status is intentionally conservative: no run is `never_run`; a successful run with no stored observation is `stale`; expired source-specific freshness is `stale`; rejected rows with usable accepted data are `partial`; and the latest failed attempt remains `failed` even if an older success exists. Phase 1 has no announcements provider, so announcements remain honestly unavailable.
