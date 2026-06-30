# PSX Market Tools

Planned read-only tools:

- `get_daily_market_snapshot(date)`
- `get_top_gainers(date, limit)`
- `get_top_losers(date, limit)`
- `get_top_volume_leaders(date, limit)`
- `get_company_price(symbol)`
- `get_company_history(symbol, start_date, end_date)`

Phase 2 implements equivalent read-only HTTP APIs under `/market`. A runtime tool registry is still deferred to a later agent/chat phase.
