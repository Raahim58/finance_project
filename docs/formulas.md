# Quant Formulas and Assumptions

- Simple return: `r_t = P_t / P_(t-1) - 1`; log return: `ln(P_t / P_(t-1))`.
- Portfolio arithmetic and risk use simple returns. Equity returns are inner-joined by observed trading date and never forward-filled.
- Annualization defaults to 252 sessions and is stored with analysis output.
- `arithmetic_expected_return` is mean daily return times 252. `realized_cagr` is compounded terminal wealth raised to `252 / observations` minus one. The legacy `annual_return` field is a compatibility alias for the arithmetic estimator, not CAGR.
- Annualized volatility is sample standard deviation times `sqrt(252)`; downside deviation is the root mean squared shortfall versus the effective daily equivalent of the selected annual target.
- Drawdown is wealth divided by its running peak minus one. Maximum drawdown is the minimum drawdown.
- Historical VaR at confidence `c` is the positive loss at the `(1-c)` return quantile; Expected Shortfall is the positive mean loss at or below that quantile.
- Alpha and beta use OLS against aligned benchmark excess returns. CAPM required return needs an effective-dated structured risk-free rate and aligned benchmark observations; it is unavailable when those inputs are absent.
- Sharpe, Treynor, Jensen alpha, M-squared, tracking error, skew, kurtosis, and concentration use the assumptions returned in each run.
- Reporting may expose sample covariance. Optimization uses diagonal shrinkage `(1-lambda) * covariance + lambda * diagonal(covariance)`, default `lambda=0.20`.
- Component/percentage risk contributions use the portfolio covariance gradient and reconcile to portfolio volatility within numerical tolerance.
- Required return solves the future-value equation from starting capital, target value, horizon, annual end-of-year contributions, and supported dated contributions. A real target is first inflated by the explicit inflation assumption. Missing objective inputs return an unavailable diagnostic rather than a guessed rate.
- Investor risk capacity and willingness remain separate. The directional reconciled tolerance is bounded by the more restrictive assessment and is stored separately from the user's confirmation.
- Current-versus-proposed analysis uses one disclosed return/covariance sample for both allocations. Historical VaR/ES in that comparison is calculated from each allocation's modeled daily return path; it is not an LLM estimate.
- Optimized and scenario results persist their input cutoff, estimator/solver, assumptions, and diagnostics. Missing samples or corporate-action state produce unavailable diagnostics, never guessed total returns.

## Remediated analytical contracts

- Operational `CASH` is not a T-bill. Its product-default nominal modeled return is 0%, its default maximum weight is 20%, and optimizer output records the return basis, effective date, minimum, maximum, and whether the maximum came from the product default or mandate/request. An explicit 100% cash maximum is the only configuration that permits the zero-variance cash solution to dominate fully.
- Risk-parity and risk-budget objectives optimize weights that sum to one inside the risky sleeve, then attach the confirmed cash minimum. API risk-budget rows expose both `total_capital_weight` and `risky_sleeve_weight`; cash appears only on the total-capital basis and has zero modeled percentage risk.
- Portfolio weights use six-decimal precision and a shared absolute sum tolerance of `1e-6` in the Build UI and comparison API. Invalid requests return the submitted sum, residual to one, and tolerance.
- The performance benchmark and CAPM market proxy are separate IPS fields. CAPM accepts only an instrument typed as an index/total-return index with `broad_market_proxy=true`; an individual equity is never silently relabeled as the market portfolio.
- Rolling Sharpe subtracts the effective annual risk-free observation for each window. Rolling beta uses the aligned performance-benchmark return window; unavailable inputs remain null with an explicit diagnostic. The return series is labeled `modeled_current_allocation`, not ledger history.
- Skew uses the bias-corrected Fisher-Pearson estimator. Kurtosis uses the matching bias-corrected excess-kurtosis estimator. Samples with zero variance return both higher moments as unavailable rather than zero.
- Comparison/frontier API return and volatility values are annual decimals. Beta, Sharpe, HHI, skew, and kurtosis are unitless ratios. Frontend formatters consume the returned unit rather than inferring it from a metric name.

This contract change adds no database columns and therefore needs no new migration. Existing environments still run the standard migration command before deployment:

```bash
cd apps/api
alembic upgrade head
```

Historical portfolio performance replays all historically held symbols plus settlement-aware cash, removes external flows from subperiod returns, and chains time-weighted returns. Cash is portfolio value, never unrealized stock profit. Legacy history starts at the migration baseline unless its transactions reconcile; no earlier cash or performance is invented.
