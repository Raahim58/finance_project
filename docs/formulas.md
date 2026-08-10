# Quant Formulas and Assumptions

- Simple return: `r_t = P_t / P_(t-1) - 1`; log return: `ln(P_t / P_(t-1))`.
- Portfolio arithmetic and risk use simple returns. Equity returns are inner-joined by observed trading date and never forward-filled.
- Annualization defaults to 252 sessions and is stored with analysis output.
- Annualized volatility is sample standard deviation times `sqrt(252)`; downside deviation uses returns below the selected target.
- Drawdown is wealth divided by its running peak minus one. Maximum drawdown is the minimum drawdown.
- Historical VaR at confidence `c` is the positive loss at the `(1-c)` return quantile; Expected Shortfall is the positive mean loss at or below that quantile.
- Alpha and beta use OLS against aligned benchmark excess returns. CAPM required return needs an effective-dated structured risk-free rate and aligned benchmark observations; it is unavailable when those inputs are absent.
- Sharpe, Treynor, Jensen alpha, M-squared, tracking error, skew, kurtosis, and concentration use the assumptions returned in each run.
- Reporting may expose sample covariance. Optimization uses diagonal shrinkage `(1-lambda) * covariance + lambda * diagonal(covariance)`, default `lambda=0.20`.
- Component/percentage risk contributions use the portfolio covariance gradient and reconcile to portfolio volatility within numerical tolerance.
- Optimized and scenario results persist their input cutoff, estimator/solver, assumptions, and diagnostics. Missing samples or corporate-action state produce unavailable diagnostics, never guessed total returns.

Historical portfolio performance replays dated ledger positions and cash. Legacy history starts at the migration baseline unless its transactions reconcile; no earlier cash or performance is invented.
