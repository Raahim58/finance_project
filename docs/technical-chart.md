# Individual-stock technical chart

The company overview contains one technical canvas using the existing ECharts 6.1.0 and echarts-for-react 3.0.6 dependencies. Default: daily candles and volume; all price overlays, lower indicators, and signals are off. The sidebar retains the latest quote, labelled separately from daily history.

## Data boundary

`GET /market/company/{symbol}/history` is the only candle/volume input. The existing optional `start_date`, `end_date`, and `limit` parameters are exposed by the frontend client without changing the backend. Backend decimal strings are converted to numbers, records sorted ascending, and malformed dates, inconsistent OHLC, missing/nonfinite prices, negative volume, and duplicate dates excluded with a visible count. No missing sessions, intraday candles, prices, source links, or corporate-action adjustments are manufactured. The candle adapter follows ECharts' [documented candlestick](https://github.com/apache/echarts-doc/blob/master/en/option/series/candlestick.md) `[open, close, low, high]` order.

1M/3M/6M/1Y/3Y/5Y use calendar months ending at the latest quote's date, or the current Karachi date when that date is unavailable. Requests include 550 extra calendar days before the visible start for initialization. This is a bounded warm-up buffer, not a guarantee of 200 sessions for illiquid securities. Calculations run on the fetched history before the visible slice. MAX is the available response within the existing 2,000-observation cap; it is not a guarantee of complete lifetime history. Partial coverage and insufficient history remain explicit.

The chart displays source labels, the returned latest source link, demo/synthetic labels, endpoint-reported market staleness, security lag relative to the market's latest session, and unavailable freshness status. Daily history is not replaced with an intraday quote. Values use raw stored prices; corporate actions or source revisions may affect interpretation.

## Deterministic definitions

- SMA20/50/200: arithmetic mean over complete trailing session windows.
- EMA20/50: seeded with the period's SMA, then alpha = 2 / (period + 1). Missing inputs restart initialization.
- Bollinger (20, 2): SMA20 plus/minus two population standard deviations over the same 20 sessions.
- Volume MA20: arithmetic mean of stored volume over 20 sessions, including the current session.
- MACD (12, 26, 9): EMA12 minus EMA26, with SMA-seeded EMA9 of MACD as the signal. Line starts after 26 prices; signal/histogram after 34.
- RSI14: Wilder-smoothed gains/losses over 14 changes; 100 when only gains, 0 when only losses, 50 when entirely flat. 30/70 are reference levels, not trade instructions.
- ROC12: `(close / close_12_sessions_ago - 1) * 100`; missing/zero denominator is unavailable.
- Slow stochastic (14, 3, 3): 14-session high/low raw %K, SMA3 %K, then SMA3 %D. Zero high-low spread is unavailable. 20/80 reference lines describe the oscillator.

Warm-up points are `null`, never artificial zeros. A selected series with no defined values is labelled unavailable. Only one lower pane can be selected.

## Signals and pivot clusters

Crossings require both consecutive observations and their reference values. An upper-band crossing requires previous close <= previous upper band and current close > current upper band. The lower band and MACD use the corresponding inverse/line-to-signal transitions. Volume events require a transition above 2× the current Volume MA20 from at/below the previous threshold. They are not labels attached to every large bar.

Support/resistance defaults live in `lib/technical/support-resistance.ts`: strict local high/low pivots with three neighboring sessions on each side; confirmation only after the three subsequent observations exist. Candidates from the trailing 252 sessions cluster within 1% of the running cluster mean. At least two distinct pivot sessions are required. Clusters score by touches (2 points each), normalized recency (up to 1 point), and summed relative pivot significance. At most four strongest clusters within 20% of the current close are shown. These parameters are centralized, not AI estimates.

Horizontal lines represent the latest current clusters, rather than pretending the refined cluster price was known historically. Crossing detection uses the previous session's confirmed clusters, holding that session's reference constant for the comparison. Future observations cannot change past detected events. A resistance/support name describes which side was crossed; these are approximate local reference levels, not predicted barriers.

The detector retains all events. Rendering shows the latest 12 events per active pane within the canonical date range. Price events require their Bollinger/pivot overlay; MACD events require the MACD pane; volume events require volume. Markers use actual date/value coordinates and neutral descriptive tooltips. Panning inside a canonical range does not recalculate or reinterpret events.

## Interaction and architecture

Normalization, indicators, and signals are independent TypeScript modules in `apps/web/lib/technical`. The React canvas memoizes the pipeline by fetched observations. Crosshair moves do not update React state; zoom events are tracked in a ref so wheel/drag actions do not rebuild the analytical pipeline. Candle/line and pane switches preserve zoom, range, and overlays. Range changes reset zoom to the new canonical window; Reset zoom affects only zoom.

All panes share the same category dates, linked axis pointers, and inside/slider zoom controls. The price pane remains largest. The indicator menu closes on Escape or outside click and fits mobile screens. ECharts animation is disabled. No LLM calculations or assistant contracts were added.

## Setup and validation

```sh
cd apps/web
npm ci
npm run dev
npm run typecheck
npm test
npm run build
```

Use the existing backend setup from the root README when running against stored market history. No database schema changes, migration commands, or production seed data are needed for this frontend feature. Existing backend migrations remain `cd apps/api && alembic upgrade head`.

Offline browser verification (against a locally running frontend) uses clearly labelled synthetic fixtures intercepted only inside Playwright; they never enter the deployed database:

```sh
E2E_BASE_URL=http://127.0.0.1:3000 npm run test:e2e -- technical-chart.spec.ts
```

Unit tests cover hand-checkable indicator sequences, insufficient-history behavior, crossing events, causal pivot confirmation, normalization, date ranges, cross-pane alignment, asynchronous request races, mode/zoom preservation, retry, and data-state labels. Browser tests exercise native ECharts tooltip/controls and desktop/mobile layouts.
