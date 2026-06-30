# Data Sources

The app is designed for automatic current-data ingestion. Mock data is only a development and testing fallback.

Planned source modes:

- Manual CSV or Excel import for MVP workflows
- DPS daily downloads parser where legally and technically appropriate
- Vendor/API adapter with configurable base URL and key
- Mock data generator for demos and tests: implemented in `python -m app.jobs.ingest_psx_mock --days 365`

Required runtime settings:

- `MARKET_DATA_MODE=mock|dps|vendor`
- `MARKET_DATA_REFRESH_SECONDS`

Required ingestion entrypoint:

- `python -m app.jobs.scheduler`

No paid vendor API key or secret should be committed. Data source adapters must fail gracefully when a source changes or is unavailable.

Current market tables:

- `exchanges`
- `companies`
- `market_prices`
- `market_snapshots`
- `sector_daily_stats`

Current implementation details:

- `mock` mode is implemented and intended only for development.
- `dps` and `vendor` modes are explicit adapter paths and scheduler modes, but still placeholder integrations until a real source contract is wired.
- Freshness is tracked in `market_ingestion_runs`.
- The frontend now consumes freshness status and surfaces stale/mock warnings.

Manual portfolio entry remains the MVP fallback. Future broker portfolio sync should use official APIs or partnerships, not password scraping or broker-site automation.
