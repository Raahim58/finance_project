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
| PSX DPS | Integrated + scheduled, primary prices | Current and historical OHLCV are validated, reconciled, and selected by priority. Invalid rows become quality issues. Index history, announcements, payouts, and corporate-action discovery are not yet certified complete. |
| DPS symbol-price ZIP | Disabled | Its URL was discovered from the live manifest, but ordinary direct and cookie/referer requests returned HTTP 403. No bypass is attempted. |
| PSX Financials | Integrated + daily schedule | New catalogue PDFs are content-addressed, parsed page-by-page, and indexed into public RAG. Automatic normalized `FinancialFact` table extraction is not claimed yet. |
| SCSTrade | Integrated + weekly supplemental schedule | Verified JSON history is normalized into canonical observations at lower priority than DPS. |
| SBP key indicators | Integrated + daily schedule | Raw official page HTML is retained. Policy rate and observed 3-month MTB cut-off yield are effective-dated; the latter is explicitly marked risk-free. Broader EasyData FX/reserve/monetary history still needs stable dataset contracts. |
| PBS Price Statistics | Integrated + weekly schedule | The current parser covers the official monthly SPI item workbook. Broader CPI/release/revision coverage remains incomplete. |
| World Bank Pink Sheet | Integrated + monthly schedule | Monthly commodity workbook rows are persisted with artifact provenance. |
| Mettis Global | Integrated + daily metadata schedule | Headline, canonical URL, timestamp, author, and visible summary become sourced events/documents. Article bodies are not republished. |
| Yahoo/yfinance | Degraded fallback | Unofficial `.KA` fallback only. The latest live verification hit an explicit rate limit; it must never silently outrank DPS. |
| NCCPL | Manual import only | Ordinary access returned Cloudflare HTTP 403. No browser automation or anti-bot bypass is used. |
| IMF RSS | Disabled | The current Social Hub links to an RSS directory that redirects to an error page. Re-enable only after a working official feed is observed and fixture-tested. |
| `psxdata` | Compatibility/comparison only | It wraps DPS and is not canonical. Retire after direct DPS parity is complete. |
| Vendor | Disabled placeholder | Requires an explicit verified contract and credentials. |

Fixture sidecars live under `apps/api/app/tests/fixtures/providers/`. They record URLs, methods, non-secret request fields, retrieval timestamps, original hashes, truncation status, parser versions, and use notes.

## Runtime settings

```bash
MARKET_DATA_MODE=auto
MARKET_DATA_DEFAULT_SYMBOLS=MEBL,SYS,OGDC
MARKET_DATA_REFRESH_SECONDS=300
MARKET_HISTORY_YEARS=5
MARKET_HISTORY_BOOTSTRAP_ENABLED=true
SCHEDULED_RESEARCH_ENABLED=true
SOURCE_ARTIFACT_ROOT=./data/artifacts
```

`auto` tries verified DPS first and uses Yahoo only as a labeled fallback. Exact prices, rankings, freshness, and sector statistics come from database queries. No live index value is synthesized from constituent averages.

## Commands

```bash
cd apps/api
python -m app.jobs.scheduler --once
python -m app.jobs.scheduler
python -m app.jobs.backfill_market_history --provider dps --symbols MEBL,SYS --start 2021-01-01 --end 2026-08-10
```

Manual portfolio entry remains the broker fallback. Never use password scraping or password-based broker automation.
