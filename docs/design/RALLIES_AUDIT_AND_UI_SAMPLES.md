# Rallies audit and PSX UI concept — 2026-10-06

Design exploration only. No application changes, migration, ingestion activation or investment recommendation. Public Rallies screens were inspected in Chrome with the user's permission. Existing PSX data was checked against the exported owner-scoped company-only LUCK snapshot; no personal portfolio data is sent to image generation.

## Decision

Use Rallies' research organization: compact company identity and quote; about/metrics beside a substantial chart; a cited digest and useful questions below; detailed tabs for statements and activity. Retain RAAHIM's green identity. The earlier cream/serif four-screen design is attractive but gives too much space to navigation and headings, fragments the company research, and emphasizes evaluation controls before the evidence. Use compact sans-serif section headings, thin rules, restrained surfaces and tabular numbers. Keep the serif treatment only for the wordmark if used.

Proposed tokens: paper #F8FAF8, white #FFFFFF, ink #172821, forest #245B46, mint #EAF3EC, muted red #B55348. Typography: restrained Manrope headings, Source Sans 3 body, IBM Plex Mono numerical/caption treatment. Signature: an integrated evidence strip under the chart connects the digest, original sources and optional portfolio relevance; it does not mix source facts with personal calculations.

## Tabs actually inspected

| Rallies surface | Observed behavior | PSX adaptation |
|---|---|---|
| Markets / Digest | Topic summaries, linked securities, event calendar and contextual Ask panel | Dated market/sector digest; show only sourced dates/events. Market-wide AI digest generation is a proposed capability, not already deployed. |
| Markets / Earnings | Calendar with company links and reported beat/miss labels | Verified board/result/disclosure dates; do not invent analyst expectations or beat/miss labels. |
| Markets / Insiders | Aggregated activity chart plus security/type/amount/person/date table | PSX issuer disclosures; a proper insider-transaction dataset would still need ingestion/extraction. |
| Markets / Politicians | Activity aggregation and individual trade table | Omit: no comparable verified local dataset or product need. |
| Markets / Analysts | Date/ticker/firm/action/rating/target table | Omit until sourced coverage exists; never substitute model-generated price targets. |
| Market lists: Indices, Trending, Gainers, Losers, Popular | Collapsible security lists with changes | Use actual index/movers/volume/sector data. Popularity/trending needs a defined observed signal. |
| Company / Chart | About, quote, key metrics, peer list, chart/volume, timeframe/line/candle/indicator/compare controls, digest, questions | Primary company overview with EPS and period-labelled ratios; optional assistant panel. Indicators/peer comparisons need deterministic inputs and methods. |
| Company / Financials | Revenue/profit charts, quarterly/yearly switch, wide period table, statement/metric expansion, export controls | Income statement, balance sheet and cash flow; basis/period/unit controls; historical ratios and source links. Show unavailable rows as unavailable. |
| Company / Funds | Institutional-position changes across quarters and ownership charts | No equivalent reliable local ownership history currently available. Free float is not institutional ownership. |
| Company / Politicians | Named transactions, dates, amounts, calculated gains | Omit. |
| Company / Insiders | Activity plot plus person/date/type/value/shares/price/shares-after table | A later verified insider ledger; current announcements alone are not that ledger. |
| Company / Analyst | Consensus/target chart and firm/analyst/action/target/upside history | Requires independent sourced analyst coverage; not implemented. |
| Company / News, Community, AI report routes | Advertised routes inspected; they returned to the company summary UI in this session | Build explicit News and Research views if chosen. Do not claim these were independent functioning reference tabs. |
| Portfolio / Digest | Net-worth chart, account grouping, contextual holding-related summaries | Selected PSX portfolio, performance/benchmark, cash, holdings and relevant evidence; label demo accounts. |
| Portfolio / Positions | Position/value/cost/quote/PnL table | Existing stored holdings and deterministic values; preserve calculation basis. |
| Portfolio / Activity | Opening the control showed a connection modal | Could not inspect the populated activity view without connecting an account. Our proposed activity layout uses existing ledger/research events, with illustrative entries labelled. No broker connection was made. |
| Watchlist | Empty-state topic onboarding; no list created | Optional explicit company watchlist; not current arbitrary portfolio selection. |

Reference pages: [Markets](https://rallies.ai/home/markets), [company overview](https://rallies.ai/research/TSLA/summary), [financials](https://rallies.ai/research/TSLA/financials), [funds](https://rallies.ai/research/TSLA/funds), [insiders](https://rallies.ai/research/TSLA/insiders), [analysts](https://rallies.ai/research/TSLA/analysts).

Some reference charts exposed `$NaN`; the overview and analyst tab showed different consensus summaries. These are observed limitations, not diagnosed causes. Design quality is not evidence of financial accuracy.

## What the samples may show honestly

Stored quote date 2026-10-02: LUCK price PKR 410.56, change -0.60%, volume 837,001, market capitalization PKR 601.4704B, ordinary shares 1.465B, free float 439.5M. KSE-100 168,155.49, change -481.36 / -0.2854%; KSE100PR 50,669.56. Observed trading volume 491,541,463 across 467 stored securities; this is not certified full-exchange volume. Sum of close × volume is an estimated value proxy, not reported turnover.

LUCK consolidated FY ending 2025-06-30: gross revenue PKR 559.204434B, net revenue 449.629947B, gross profit 122.737896B, operating profit 97.924B, net income 84.498377B, assets 729.361628B, total equity 388.041438B, total debt 191.504104B, cash 131.669488B, reported EPS PKR 52.53. Source: retained LUCK annual report 2025. These are snapshot records, not a new source re-audit or complete certified statements.

Possible deterministic calculations: FY25-based P/E = 410.56 / 52.53 = 7.82x (not TTM); debt/equity = 191.504104 / 388.041438 = 0.49x; gross profit/net revenue = 27.30%. Their production implementation must validate selected facts, share/split basis and periods. Do not use consolidated total equity as parent attributable equity for P/B without checking it. ROE needs an explicit denominator convention; average-equity ROE requires both beginning and ending equity. TTM EPS needs compatible interim periods. Dividend yield needs verified cash-per-share amounts; a 250%-of-par announcement is not a 250% yield.

Existing inputs can support properly adjusted daily charts, dated share metrics, historical financial tables where facts are valid, source-linked research, volatility/drawdown/VaR/beta where inputs exist, portfolio weights and stress/proposal calculations. Current statement coverage, parsing quality, news relevance, corporate-action completeness and digest accuracy remain limitations. Mock chart paths and mock activity entries must carry a design/illustrative label. No invented complete historical statements or forward earnings estimates.

## Requested samples

1. Company overview: compact quote/about/key metrics, substantial price/volume chart, saved research, sources, and optional contextual Ask panel.
2. Financials: income/balance/cash-flow sub-tabs, basis and annual/interim selectors, exact available values and gaps, ratio definitions and source drill-down.
3. Paired market + portfolio views: market digest/context/movers, and portfolio performance/holdings/activity/risk navigation. Risk/stress data stays distinguishable from observed prices and disclosed financial facts.

Generated using the built-in image-generation tool. Full prompt specifications accompany saved sample files; these are visual concepts, not production screenshots.

Final images:

- [Company overview](../../output/ui-concepts/rallies/company-overview-v2.png)
- [Company financials](../../output/ui-concepts/rallies/company-financials.png)
- [Markets and portfolio activity/risk](../../output/ui-concepts/rallies/markets-portfolio-v2.png)

[Original prompts](../../output/ui-concepts/rallies/PROMPTS.md) and [text refinements](../../output/ui-concepts/rallies/REFINEMENTS.md) are saved alongside them. Final images were inspected: an unsupported earnings-driver sentence was removed and a generated label incorrectly calling KIBOR the policy rate was corrected. The financial preview retains period, basis, units, source labels and explicit gaps. Do not treat image-generated typography, charts or mock activity as verified application output.
