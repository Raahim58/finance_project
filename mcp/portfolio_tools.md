# Portfolio Tools

Planned read-only and calculation tools:

- `get_user_portfolio(user_id, portfolio_id)`
- `get_portfolio_summary(user_id, portfolio_id)`
- `calculate_sector_exposure(user_id, portfolio_id)`
- `calculate_holding_pnl(user_id, portfolio_id, symbol)`
- `simulate_order_impact(user_id, portfolio_id, symbol, side, amount)`
- `list_watchlist(user_id)`

Phase 3 implements equivalent protected HTTP APIs for portfolios, holdings, transactions, summary, exposure, performance, and risk flags. Runtime MCP tools and watchlists are still deferred.
