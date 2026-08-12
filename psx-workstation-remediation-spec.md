# PSX Workstation — Codex Remediation Specification

**Purpose:** implementation-ready engineering plan derived from the live product, finance-math, and repository audit.  
**Repository:** `Raahim58/finance_project`  
**Priority rule:** correctness and evidence semantics before new charts or ratios.  

## 1. Definition of done

The workstation is ready for another decision-support review only when:

1. Every quantitative value has an explicit unit, basis, date range, data cutoff, and run/model ID.
2. `PASS`, `BREACH`, and `NOT_EVALUATED` survive unchanged from service to UI.
3. Build, Risk, Quant, Scenario, and Assistant use compatible allocation denominators and model assumptions or explicitly identify differences.
4. No optimizer can exploit an economically impossible cash assumption.
5. Analyzer answers the requested intent using relevant structured facts; document evidence is included only when relevant.
6. A security-to-research handoff applies a real symbol filter, not merely a text hint.
7. Every asynchronous screen reaches success, empty, or error state without stale-response overwrites.
8. Golden finance fixtures and cross-page reconciliation tests pass in CI.

## 2. First implementation changes

### 2.1 Create shared analytical metadata

Add a reusable API schema, for example:

```python
class MetricValue(BaseModel):
    value: float | None
    unit: Literal["decimal", "percentage_point", "ratio", "PKR", "days", "count"]
    status: Literal["AVAILABLE", "NOT_EVALUATED"]
    reason: str | None = None
    sample_start: date | None = None
    sample_end: date | None = None
    data_cutoff: date | None = None
    observations: int | None = None
    annualization: int | None = None
    return_basis: Literal["price", "total_return", "ledger_twr", "modeled_current_allocation"] | None = None
    portfolio_basis: Literal["total_capital", "risky_sleeve"] | None = None
    estimator: str | None = None
    run_id: str | None = None
```

Do not attempt a one-shot migration of every endpoint. Introduce this contract for comparison/frontier/risk first, then migrate remaining metrics. Frontend formatters must consume `unit`; components must not infer units from metric names.

### 2.2 Add one compliance presentation model

Create a single component and mapping function that accepts `status`, `checks`, `violations`, and `not_evaluated`. Remove UI decisions based solely on `compliant` or `violations.length`.

Required mapping:

| Service state | UI label | Tone | Meaning |
|---|---|---|---|
| `PASS` | Within evaluated mandate | green | All required, evaluable checks passed |
| `BREACH` | Mandate breach | red | At least one evaluated hard constraint failed |
| `NOT_EVALUATED` | Not fully evaluated | amber | Required data/model inputs are missing |

`NOT_EVALUATED` must list each missing input. It must never be called compliant or a breach.

## 3. Detailed repair tickets

## F-01 — Cash creates degenerate optimizer solutions

**Severity:** Critical  
**Locations:** `apps/api/app/services/workstation_service.py:598–618`, comparison cash logic around `decision_analytics_service.py:352–364`.

### Current failure

The optimizer appends `CASH` with a constant zero return series and therefore zero covariance, while assigning it the observed annual T-bill rate. Its upper bound is 100%. Minimum-variance and required-return runs therefore converge to almost all cash with positive expected return and approximately zero volatility.

### Required implementation

- Separate operational cash from an investable short-duration government instrument.
- Operational cash may have zero modeled volatility but should use an explicit conservative cash yield and a mandate-defined maximum, not inherit a T-bill yield automatically.
- If T-bills are investable, model them as an instrument with an effective-duration/reinvestment return series and explicit provenance.
- Add `max_cash_weight` to constraints. If absent, use a documented product default and disclose it.
- For required-return minimum variance, reject an economically invalid feasible set rather than returning a misleading solution.
- Risk parity/risk budget should optimize the risky sleeve and attach the constrained cash sleeve separately.
- Store nominal/real basis and effective date for the cash-return assumption.

### Acceptance tests

- Positive cash yield plus zero variance cannot dominate the portfolio unless an explicit 100% cash mandate permits it.
- Required return, min/max cash, instrument caps, sector caps, and weight sum all hold within one shared tolerance.
- Risk-parity and risk-budget objectives run with a confirmed cash minimum.
- Diagnostics explain infeasibility and name binding constraints.

## F-02 — Compliance states collapse into false pass/breach labels

**Severity:** Critical  
**Locations:** `WorkspacePage.tsx:119, 157, 190, 195`; `DecisionTables.tsx:11–13`; `compliance_service.py:130–145`.

### Required implementation

- Replace boolean-derived badges with the three-state presentation model.
- `ComplianceTable` must accept all checks, not only violations.
- Add separate sections for hard breaches and unavailable checks.
- Stressed compliance must retain the same states.
- A proposal can be saved while not evaluated, but the record must retain the missing checks and cannot be labeled compliant.

### Tests

- No breaches + four unavailable checks renders `Not fully evaluated`.
- Empty violations never implies PASS.
- Scenario, Risk, Build, and IPS show identical state for the same compliance response.

## F-03 — CAPM/SML treats any benchmark as the market portfolio

**Severity:** High  
**Location:** `decision_analytics_service.py:190–230`.

### Required implementation

- Split `performance_benchmark_symbol` from `capm_market_proxy_symbol` in the IPS/model configuration.
- Validate a CAPM proxy against approved broad-index instruments.
- Prefer total-return index series when available; otherwise mark limitations.
- Show market risk premium explicitly and warn when it is negative.
- Do not label HBL or another individual security “Market return.”
- Persist risk-free series key, observation dates, beta regression window, and alignment diagnostics.

### Tests

- Individual-equity benchmark cannot silently become the CAPM market proxy.
- SML endpoints and plotted points use the same decimal scale.
- Betas and Jensen alpha reconcile to a golden regression fixture.

## F-04 — Risk-budget tables mix total-capital and risky-sleeve weights

**Severity:** High  
**Locations:** `decision_analytics_service.py:421–443`; `WorkspacePage.tsx:193–194`.

### Required implementation

- Return both `total_capital_weight` and `risky_sleeve_weight`.
- Include cash as a row where total-capital weights are displayed.
- Rename existing fields; avoid the ambiguous `capital_weight`.
- Compare current and proposed values only on the same basis.
- Add a response-level `portfolio_basis` field.

### Tests

- Total-capital weights including cash sum to one.
- Risky-sleeve weights excluding cash sum to one.
- Changing cash alone does not change risky-sleeve proportions or security percentage risk.

## F-05 — Holding-to-evidence and RAG filtering are inconsistent

**Severity:** High  
**Locations:** `companies/[symbol]/page.tsx:23`; `research/page.tsx:11–12`; `rag_service.py:412–492`.

### Current failure

The company page routes to `/research?symbol=ABOT`. Research copies `ABOT` into the query field but calls `searchRag` without `symbols:["ABOT"]`. The live ABOT search returned no passages even though ABOT documents existed and Analyzer cited one. Other security searches returned low-score documents belonging to unrelated companies.

### Required implementation

- Parse and validate the symbol from the URL.
- Send `symbols: [symbol]` in `RagSearchRequest` until the user explicitly clears the company scope.
- Display a removable `ABOT` scope chip.
- Resolve names/symbols through the instrument service before retrieval.
- Apply hard symbol filtering before vector/lexical ranking.
- Define a minimum relevance threshold and return insufficient evidence below it.
- Remove `demo://` open-source links or route them to an internal document viewer.
- Use the same retrieval service and filtering contract in Research and Analyzer.

### Tests

- ABOT handoff returns only ABOT chunks.
- Removing the scope chip enables market-wide search.
- A nonexistent symbol produces a clear empty state.
- Search does not pad to `limit` with irrelevant documents.

## F-06 — Analyzer ignores question intent and adds irrelevant citations

**Severity:** High  
**Locations:** `assistant/page.tsx:9–17`; `ai/orchestrator.py:42–80, 174–256`.

### Current failure

For “where is the risk concentrated in my portfolio,” Analyzer returned total portfolio value, cash, and a generic note that risk metrics were calculated. It did not identify SYS/MEBL or risk contributions. It attached eight unrelated synthetic documents. A market-wide question was also changed to portfolio scope after the asynchronous portfolio list loaded.

### Required implementation

- Never auto-change scope after the user has typed or submitted. Initialize once or require explicit selection.
- Capture `{question, portfolio_id, scope_version}` atomically at submit.
- Add deterministic intent handlers before generic fallback:
  - risk concentration;
  - performance/attribution;
  - mandate compliance;
  - market overview/breadth/freshness;
  - holding/company evidence;
  - scenario explanation.
- A risk-concentration response must contain top capital weights, top percentage-risk contributors, HHI/effective holdings, total-vs-risky-sleeve basis, model cutoff, and missing inputs.
- Do not invoke narrative search for a purely structured question unless the question asks “why,” “what changed,” filings, management, or events.
- Require every citation to pass symbol/entity and relevance gates.
- Preserve the claim/evidence validator, but validate relevance and intent coverage as well as citation IDs.

### Acceptance test example

Given the audited demo portfolio, a risk-concentration answer must identify SYS and MEBL as the largest modeled risk contributors, distinguish their total capital weights from risky-sleeve weights, state the covariance cutoff, and attach zero unrelated filings.

## F-07 — Efficient frontier can remain in loading state

**Severity:** High  
**Location:** `WorkspacePage.tsx:126–136`.

### Root cause

The effect depends on `details`. A successful request updates `details`, causing cleanup to set `active=false` before `.finally` clears `loadingTab`.

### Required implementation

- Remove `details` from the request effect dependency.
- Track loaded tab IDs with a ref, reducer, or query library.
- Model each tab as `idle | loading | success | empty | error`.
- Clear loading in the same state transition that stores success/error.
- Add timeout and retry UI.

### Tests

- Every analytics tab reaches a terminal state.
- Switching tabs during an in-flight request cannot leave a permanent skeleton.
- Stale responses cannot overwrite the currently selected tab.

## F-08 — Rolling Sharpe assumes zero risk-free; rolling beta is always null

**Severity:** High  
**Location:** `decision_analytics_service.py:254–280`.

### Required implementation

- Align the effective-dated risk-free series with each rolling window.
- Calculate `(annualized return - annualized risk-free) / annualized volatility`.
- Calculate rolling beta from aligned benchmark returns or return `NOT_EVALUATED` with the exact reason.
- Rename the modeled series correctly; it is not ledger history.
- Return window length, observations, benchmark, and risk-free provenance.

## F-09 — Advertised optimizer objectives are unusable under normal defaults

**Severity:** High  
**Location:** `workstation_service.py:598–600, 629–650`; Build controls.

### Required implementation

- Define compatibility rules for objective × expected-return method × cash constraints.
- Target-beta must either compute betas independently or require/auto-select CAPM with a clear explanation.
- Risk parity/risk budget must use risky-sleeve formulation plus cash constraint.
- Disable impossible combinations before API submission.
- Return structured diagnostics rather than only a message string.

## F-10 — Synthetic/mock facts look like observed fundamentals

**Severity:** High  
**Locations:** Market/company pages and seed data presentation.

### Required implementation

- Add persistent page-level `MOCK / SYNTHETIC` banners.
- Attach source, as-of, ingestion timestamp, and synthetic flag to each fact group.
- Prevent production configuration from serving demo facts without an unmistakable environment flag.
- Add an internal provenance drawer for normalized facts and derived ratios.

## P-01/P-02 — Scenario state and labels

**Locations:** `WorkspacePage.tsx:161–169`.

- Initialize with no result, or hydrate controls from the selected persisted run.
- Use one authoritative result panel.
- Invalidate/refetch history after every run.
- Show shock precedence: security overrides sector overrides factor, where applicable.
- Give every control a unique `id`/`htmlFor`; do not nest two controls under one label.
- Persist and display scenario version, model cutoff, assumptions, and current/proposed portfolio basis.

## P-03/P-14 — Unit formatting failures

**Locations:** Risk beta display and Build trade-offs.

- Portfolio beta is unitless; render `0.25`, not `+24.55%`.
- Sharpe delta `-0.773` must not render as `-77.3%`.
- Use the shared `MetricValue.unit` formatter.
- Add snapshot tests covering decimal, percentage-point, ratio, and currency values.

## P-04 — Zero delta is labeled “Worsened”

**Location:** `DecisionTables.tsx:16–17`.

- Introduce `UNCHANGED` with metric-specific or shared tolerance.
- Distinguish statistically/economically immaterial changes where uncertainty is available.
- Ensure trade-off list and comparison table use the same classification function.

## P-05 — Allocation charts omit cash without saying so

- Use total-capital allocation by default.
- Include cash as a slice or explicitly label a risky-sleeve chart.
- Show the denominator in tooltips and exported data.

## P-06 — Market company search can show stale unfiltered results

**Severity:** Medium  
**Locations:** `apps/web/app/market/page.tsx:12–15`; `apps/web/lib/api.ts:454–457`; backend route `market.py:95–101`; service `market_service.py:212–218`.

### What happened

Typing `MEBL` left the original roughly 20-company directory visible and produced no MEBL link. The input accepted the query, so the screen looked filtered even though its rows were stale.

### Why this needs improvement

The backend path is correct in isolation:

- frontend sends `/market/companies?q=MEBL`;
- route accepts `q`;
- service applies case-insensitive symbol/name `LIKE` filtering.

The frontend has competing, unguarded writes:

1. The mount effect calls unfiltered `getCompanies()` inside `Promise.all`.
2. The query effect also runs immediately for the empty query and calls unfiltered `getCompanies("")`.
3. Typing starts a third request for `MEBL`.
4. Every request calls `setCompanies(rows)` when it resolves; there is no `AbortController`, request sequence, query check, or stale-response guard.

Therefore an older, slower unfiltered response can overwrite the newer MEBL result. The duplicate initial request is unnecessary and increases the race probability. The UI also does not show which query produced the current rows.

### Required implementation

- Remove `getCompanies()` from the initial `Promise.all`; let one query-driven loader own directory state.
- Debounce the normalized query.
- Cancel the previous request or attach a monotonically increasing request ID.
- Only commit a response if its query/request ID is still current.
- Track directory state separately from the market-overview loading/error state.
- Show `Results for “MEBL”`, loading, zero-results, and request-error states.
- Preserve old rows only if labeled stale; preferably show a skeleton while the active query is loading.
- Optionally prioritize exact-symbol matches in backend ordering.

### Suggested frontend pattern

```tsx
const requestId = useRef(0);

useEffect(() => {
  const id = ++requestId.current;
  const controller = new AbortController();
  const timer = setTimeout(async () => {
    setDirectoryState({status: "loading", query, rows: []});
    try {
      const rows = await getCompanies(query, {signal: controller.signal});
      if (id === requestId.current) {
        setDirectoryState({status: "success", query, rows});
      }
    } catch (error) {
      if (!controller.signal.aborted && id === requestId.current) {
        setDirectoryState({status: "error", query, rows: [], error: toMessage(error)});
      }
    }
  }, 250);
  return () => { clearTimeout(timer); controller.abort(); };
}, [query]);
```

Update the API request wrapper to accept `AbortSignal`.

### Tests

- Unit: `search_companies("MEBL")` returns MEBL and no unrelated symbols.
- API: `GET /market/companies?q=MEBL` is case-insensitive.
- Component: delayed unfiltered response resolving after MEBL cannot overwrite MEBL.
- Component: fast `M` → `ME` → `MEBL` changes display only the final response.
- E2E: search a symbol outside the first unfiltered 20; assert result count, exact link, and absence of original rows.

## P-07 — Monitoring acknowledgements disappear from view

- Add Active, Acknowledged, Resolved, and All filters.
- Persist actor, timestamp, note, and previous/new states.
- Link the event into the unified activity timeline.

## P-08 — Mobile primary navigation disappears

- Add a labeled menu button and focus-trapped drawer.
- Retain current route and portfolio context.
- Test all main routes at 390×844 with keyboard and screen-reader roles.

## P-09 — Slow route transitions

- Measure a production build, not the Next.js dev preview.
- Instrument endpoint timing and client waterfalls.
- Remove duplicate fetches, batch workspace requests where safe, and cache immutable IPS/allocation records.
- Define route-level time budgets and show meaningful loading/error states.

## P-10 — “Stale” conflates mock mode and ingestion age

- Return and render separate fields: provider mode, ingestion age, trade-date status, fallback provider, and exchange-session status.
- “Snapshot available” is not market status.

## P-11 — Activity is not a complete audit trail

- Keep the transaction ledger but add an immutable event stream for IPS confirmation, optimizer run, proposal save/revision, recommendation transition, scenario run, alert acknowledgement, and assumption change.
- Each event requires actor, timestamp, entity ID/version, before/after or immutable snapshot link, cutoff/source, and rationale/note.
- Clarify why opening-balance securities show PKR 0 gross amount despite quantity and price, or display an opening market/cost value instead.

## P-12 — Invalid portfolio scope conflicts with selector

- On 404, reconcile to the selected valid portfolio or disable portfolio links.
- Never display a valid portfolio selector while keeping invalid-ID links.

## P-13 — UI and API disagree about whether weights sum to 100%

**Locations:** Build client validation around `WorkspacePage.tsx:108–110`; server `decision_analytics_service.py:337–341`.

- Define one shared tolerance constant.
- Normalize or quantize weights at a documented decimal precision.
- Show exact residual and provide “Normalize to 100%.”
- Server error must return submitted sum and residual.
- Test displayed two-decimal untouched weights combined with edited weights.

## P-15 — Frontier labels, units, and feasible set are unclear

**Locations:** `WorkstationChart.tsx:70–73`; `decision_analytics_service.py:128–187`.

- Give Current, Global Minimum Variance, and Maximum Sharpe separate series, colors, shapes, and persistent labels.
- Include a chart-adjacent numeric table for accessibility and verification.
- Validate expected-return/volatility ranges and surface unit-contract errors rather than plotting implausible 500% axes.
- Apply the same feasible set as Build, or title the chart `Unconstrained risky-sleeve comparison`.
- Include cash/sector/eligibility caveats next to the title, not only below the chart.
- Add screenshot tests with fixed data and API contract tests asserting decimal—not percentage-point—values.

## P-16 — Skew/kurtosis estimator and degenerate samples

**Location:** `domain/quant/metrics.py:128–157`.

- Use a consistent documented biased or bias-corrected estimator.
- Do not mix population central moments with sample standard deviation silently.
- Return unavailable for a zero-variance sample rather than skew/kurtosis zero.
- Display observations and estimator.
- Add bootstrap confidence intervals if higher moments will influence decisions.

## 4. Additional analytics after remediation

Do not implement these until the blockers above pass:

- Drawdown duration/recovery and contribution-to-drawdown.
- Rolling VaR/ES and marginal/component VaR.
- Sortino using IPS required return or explicit minimum acceptable return; Calmar; information ratio versus a valid benchmark.
- Rolling correlation/beta and covariance-regime stability.
- Confidence bands and assumption sensitivity on the frontier.
- Position/ADV, liquidation days, spread/impact, and stressed liquidity.
- Factor, sector, currency, and interest-rate exposure.
- Reverse stress testing and scenario contribution waterfalls.
- Proposal turnover, transaction costs/taxes, lot sizes, drift, implementation shortfall, and constraint shadow prices.
- Recommendation owner, expiry/recheck date, quantified trigger/current/limit, expected effect, uncertainty, disposition rationale, and linked run IDs.

## 5. Test architecture

### Golden quant fixtures

Create small deterministic price/return fixtures with independently calculated expected results for:

- required return with and without contributions;
- TWR and CAGR;
- annualized arithmetic return/volatility;
- max drawdown and recovery duration;
- beta, alpha, tracking error, and information ratio;
- VaR/ES at 95% and 99%;
- skew and excess kurtosis;
- covariance/correlation and percentage risk contribution;
- optimizer objectives and infeasibility diagnostics.

### Invariants

- Weights and total-capital allocation reconcile to one.
- Every constraint is satisfied or the result is not `optimal`.
- Risk contributions reconcile to 100% when portfolio volatility is non-zero.
- Same inputs/run ID produce identical values across pages.
- No required unavailable check can produce PASS.
- Identical allocations produce `UNCHANGED`.
- No stale async response can replace newer query state.

### End-to-end journeys

1. Holding → company page → symbol-scoped evidence → cited document.
2. Portfolio question → risk-concentration Analyzer answer → linked Quant evidence.
3. Manual weight edit → normalize → compare → save immutable proposal → Activity event.
4. Recommendation → Build proposal → reviewed/resolved transition → audit trail.
5. Scenario definition → run → matching result → refreshed history → stressed compliance.
6. Frontier/rolling/distribution tabs → terminal state with correct labels and units.

## 6. Suggested pull-request sequence

1. **PR 1:** metric units, shared tolerances, and three-state compliance components.
2. **PR 2:** optimizer cash/risky-sleeve formulation and objective compatibility.
3. **PR 3:** risk-budget denominators, beta/Sharpe/higher-moment corrections.
4. **PR 4:** frontier state machine, feasible-set disclosure, labels, and chart tests.
5. **PR 5:** symbol-scoped RAG and company-to-research handoff.
6. **PR 6:** Analyzer intent routing, scope locking, and citation relevance gates.
7. **PR 7:** scenario state/accessibility and market-search request ordering.
8. **PR 8:** unified activity timeline, recommendations, and monitoring history.
9. **PR 9:** mobile navigation, provenance hardening, and performance instrumentation.

Each PR should include migrations if needed, API/schema updates, frontend changes, unit/integration tests, and a short reconciliation note showing before/after numerical behavior. Avoid mixing cosmetic redesign with finance-model corrections.
