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

No endpoint, form field, selector, download URL, unit, or date convention may be guessed. Raw responses from enabled ingestion runs are stored content-addressed under `SOURCE_ARTIFACT_ROOT`; the database records source URL, SHA-256, parser version, content type, effective time, and storage path.

## Provider status

| Source | Status | Observed contract and precedence |
|---|---|---|
| PSX DPS | Enabled, primary | `GET /symbols`; `POST /historical` with either `date` or `month/year/symbol`; `POST /daily-downloads`; `GET /timeseries/eod/{symbol}`. DPS date-wise OHLCV is canonical. Impossible rows are quarantined. |
| DPS symbol-price ZIP | Disabled | Its URL was discovered from the live manifest, but ordinary direct and cookie/referer requests returned HTTP 403. No bypass is attempted. |
| PSX Financials | Enabled | `POST annQtrStmts.php` using observed `get_yearly_data`, `get_comp_data`, and `get_comp_y_data` forms. Report links are accepted only when they match the observed `lib/DownloadPDF.php?id=...` contract and return a PDF. |
| SCSTrade | Enabled, supplemental | JSON POST to `MS_HistoricalPrices.aspx/chart` with `par`, `date1`, and `date2`. Form encoding returned HTML and is not used. Never outranks DPS. |
| PBS Price Statistics | Enabled | Workbook URL discovered from the current official catalog; `Items 1-51` title/header/average-price contracts are validated. |
| World Bank Pink Sheet | Enabled | Monthly workbook URL discovered from the current official catalog; `Monthly Prices` title/update/name/unit rows are validated. |
| Mettis Global | Enabled, metadata only | Static `/latest/` listing plus per-article `NewsArticle` JSON-LD. Store headline, canonical URL, timestamp, author, and visible summary only—not article bodies. |
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
SOURCE_ARTIFACT_ROOT=./data/artifacts
```

`auto` tries verified DPS first and uses Yahoo only as a labeled fallback. Exact prices, rankings, freshness, and sector statistics come from database queries. No live index value is synthesized from constituent averages.

## Commands

```bash
cd apps/api
python -m app.jobs.scheduler --once
python -m app.jobs.scheduler
```

Manual portfolio entry remains the broker fallback. Never use password scraping or password-based broker automation.
