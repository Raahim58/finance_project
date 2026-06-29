# Data Sources

Phase 1 does not ingest PSX, company, macro, or policy data yet.

Planned source modes:

- Manual CSV or Excel import for MVP workflows
- DPS daily downloads parser where legally and technically appropriate
- Vendor/API adapter with configurable base URL and key
- Mock data generator for demos and tests

No paid vendor API key or secret should be committed. Data source adapters must fail gracefully when a source changes or is unavailable.
