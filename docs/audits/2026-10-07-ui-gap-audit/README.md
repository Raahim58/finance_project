# Live UI, supplied designs, and Rallies comparison

Audit date: **7 October 2026, Asia/Karachi**. Target: running Oracle deployment through `http://localhost:13000`, Chrome at its existing approximately 1384 × 819 viewport. This is an audit and implementation brief, not a completed redesign.

## Finding

The disappointment is supported by observable defects. The application has substantial portfolio and research machinery, but its read contracts, operational reliability, information hierarchy, and visual system do not produce the experience in the supplied images. Repainting the current pages would preserve several incorrect states.

The first repair should address market-session selection, database failures, financial-fact eligibility, and unknown compliance states. The visual work should then use one compact white/navy workstation system across every route, with briefs connected to securities, portfolio exposure, evidence, and contextual Assistant questions.

## Evidence and scope

- Inspected live Dashboard, Markets, selected portfolio Overview, Build, Quant, Risk, FFC company research, Research, Monitoring, Settings, and the existing Assistant conversation. Inspected authenticated Rallies Chat and Today → Markets/Digest. Read the supplied Markets, portfolio Overview, Build, Quant, Risk, Research, and Monitoring images.
- Read local source and relevant domain documentation. The working tree already contained ongoing backend/pipeline changes; they were not edited. Local code references below explain possible repair locations; no claim is made that every uncommitted local change is deployed.
- Read current API container exceptions and executed database reads inside read-only transactions. `SET LOCAL max_parallel_workers_per_gather=0` was used for those diagnostic sessions only. No persistent database configuration changed.
- Ran one default Build optimization successfully. The action **automatically saved** allocation `9de731af-0440-4b62-bd9b-0cf5d8ec2fb2`. The UI confirmed no trades; no Save sandbox action was taken, and holdings/transaction ledger were not edited. This automatic save should itself be clarified in the product flow.
- No fresh Assistant prompt, event-generation batch, provider-key write, migration, ingestion backfill, deployment, or service restart was requested. The company page's normal read can activate its existing brief refresh behavior.
- No mobile verification, complete objective-by-objective optimizer validation, source-PDF reconciliation, or fresh AI synthesis/entailment test was performed. An existing answer is evidence of rendered behavior, not proof that its claims are correct.

Artifacts: [Build result](build-result.jpg), [Build DOM](build-dom.txt), [Markets capture](markets.jpg), [Risk capture](risk.jpg), [FFC capture](ffc.jpg). Browser captures can reflect intermittent failures/loading; the observations below also record successful reads earlier in the audit.

## Confirmed problems and repair direction

| Priority | Area | Observed behavior | Diagnosis and concrete repair |
|---|---|---|---|
| P0 | Market coverage | Movers contain only LUCK and FFC; sectors and snapshot totals disappear. | Default market date resolves to **7 Oct** from two intraday instruments. The broad daily session remains **2 Oct**. Select a dated broad-market dataset using a documented coverage rule; show newer per-security quotes separately. Never imply a partial quote sample is the full market. |
| P0 | Freshness | Dashboard/footer report **13 Aug**, index/history **2 Oct**, company quote **7 Oct**. | `get_market_freshness()` reads legacy ingestion-run/snapshot metadata while canonical reads use observations/artifacts. Derive freshness from the exact dataset displayed, with separate observation, ingestion, and exchange-session times. |
| P0 | Operational errors | Performance, Quant, compliance, risk-budget, and portfolio-event reads fail intermittently. | Current API logs contain PostgreSQL shared-memory allocation failures during canonical `price_series()` reads. Compliance calls Quant, propagating the failure. Fix query plans/resource pressure and request fan-out; validate recovery under concurrent portfolio reads. Readiness alone did not detect this failure. |
| P0 | Financial facts | FFC Revenue row points to `SALES TAX & EXCISE DUTY`; Cash row scale conflicts with a source sentence saying billions; repeated/conflicting observations are dumped in the brief. | Validate taxonomy, unit multipliers, selected reporting column, entity, consolidation basis, duration, and statement scope. Retain suspect evidence for review but exclude it from verified ratios and advisory synthesis. Do not invent corrected amounts from this audit. |
| P0 | Compliance | Risk says **“Mandate breach” / “0 hard mandate breaches”** after compliance fails; later says **“Not fully evaluated.”** | `DecisionBanner` treats null compliance as a breach with a zero fallback. Model loading/error/not-evaluated/pass/breach explicitly. Unknown is neither a pass nor a breach count of zero. |
| P1 | Company page | FFC loads on one visit but an intermittent dependency error can replace the whole page on another. | The initial `Promise.all` includes detail, history, research, and portfolios. Load independently; retain price/company identity when research or portfolio context fails. |
| P1 | Company brief | A raw financial/statement dump is presented as the brief. Contact addresses appear under earnings drivers; signatures under material developments. | `CompanyDigestPanel` renders prepared evidence before synthesis. Put a concise validated brief first; separate reviewed narrative from prepared evidence, and move the latter into section drill-downs. Missing synthesis needs a visible state even when prepared sections exist. |
| P1 | Ratios | “Model-derived ratios” reports **“Canonical valuation inputs were not requested by this context contract.”** | The context adapter explicitly returns empty `latest/growth/ratios`. Wire an eligible structured calculation contract into company views. Missing ratios are not universally a lack of filings. |
| P1 | Risk-free | Quant shows unavailable observed risk-free series; Sharpe, Maximum Sharpe marker, and CAPM are disabled. | The resolver exists. A live read returned `None` as of **2 Oct**. Attach a sourced effective-dated risk-free series and approved CAPM proxy; disclose tenor/date/method. SBP policy rate is present elsewhere but is not automatically the designated risk-free instrument. |
| P1 | Market brief | The same five OilPrice geopolitical stories dominate Markets, Research, and Dashboard. | These are event-feed excerpts, not an integrated market briefing. The endpoint defaults to five records; the local legacy selection favors high materiality across a 90-day window. Add relevant/fresh market briefing projection, source/topic diversity, event deduplication, and source-backed reasons for selection. Check new pipeline events against the actual UI read contract. |
| P1 | Portfolio relevance | Research's “Events affecting your portfolio” fails. FFC's selected relevance mostly shows quantity/value/weight; event explanations are not generated. | Holdings exposure, event linkage, explanatory synthesis, and Security Fit are separate capabilities. Show affected holdings/weight, direct versus indirect relationship, mechanism, confidence, freshness, and cited evidence. A held badge is not a relevance analysis. |
| P1 | Build | Proposed table and delta column overlap the insights rail; objective text is clipped. | Four-column grid retains fixed 280px/270px columns until a viewport breakpoint of 1280px. Actual content width is much less after the sidebar/padding. Use container-aware layout and explicit table overflow; move insights below sooner. |
| P1 | Build results | The default run works, but its comparison reports **1 breach / 9 evaluated checks**, plus **1 unevaluated check**. | Inspect the failed check and whether solver constraints and post-comparison constraints match. Present “proposal needs review” prominently. Do not treat solver success as mandate compliance. Audit did not establish the failed check's cause. |
| P1 | Monitoring | All counts are zero with “No active exceptions,” despite obvious stale-data and analysis failures elsewhere. No rules editor appears. | Expose last monitoring evaluation, rule coverage, failures, and scope before implying all-clear. Add a rules surface over supported backend rules; unsupported rules require actual evaluator implementation. |
| P1 | Settings domain | Global Settings edits risk tolerance and horizon, and labels them an investor profile. | This conflicts with `CONTEXT.md`: investment preferences belong to a selected portfolio's confirmed IPS. Keep provider/application/notification settings global; link investment mandate controls to the selected IPS. |
| P2 | Shell and typography | RAAHIM/serif/cream shell on some routes; PX/system shell and extra topbar on Company, Research, Monitoring, Settings. Sidebar ordering changes on Dashboard. | One shell, one stable navigation order, one token system. Remove route-specific identity switches and repetitive implementation-status copy. |
| P2 | Logos | Most rows show two-letter monograms. Company header has no recognizable mark. | Current implementation depends on stored official website plus Google favicons and rejects small images. Introduce a curated sourced logo asset registry with provenance, sensible sizes, and consistent monogram fallback. Apply it to company headers, holdings, movers, briefs, and Assistant security chips. |
| P2 | Charts | Portfolio Overview has no trajectory during failure; Dashboard accessibility output includes leading NaN points; company chart is far below raw evidence. Frontier occupies a tiny part of the scale. | Distinguish ledger history from constant-weight modeled history. Filter pre-baseline gaps from the displayed interval; compress empty error panels. Put useful price/performance charts near the top with ranges, tooltips, units, provenance, and benchmark controls. Never redraw a fictional curve to look like the mockup. |
| P2 | Assistant | Fixed drawer/overlay, repeated portfolio labels, provider and token/model-call metadata in the main reading flow; malformed citation text exists in the old conversation. | Offer a full workspace plus optional contextual rail, readable answer width, compact context chips, accessible source drawer, follow-up actions, and collapsible diagnostics. Validate citation rendering and factual source support separately. |

### Database proof of the market gap

Read during this audit, not copied from a prior report:

| Read | Result |
|---|---:|
| `get_latest_market_date(db)` | 2026-10-07 |
| Distinct intraday instruments on 7 Oct | 2 |
| `_prices_for_date(db, 2026-10-02)` excluding indices | 467 |
| `get_sectors(db, 2026-10-02)` | 37 |
| `get_market_snapshot(db, 2026-10-02)` | Present |
| Default `get_sectors(db)` | 0 |
| `get_market_freshness(db).latest_trade_date` | 2026-08-13 |
| Effective observed risk-free resolver, 2 Oct | None |

Canonical daily effective timestamps were stored at `2026-10-01 19:00 UTC`, which is **2 Oct midnight PKT**. A UTC date cast must not be mistaken for the PSX trade date. Explicit `date=7 Oct` sector resolution also rejected the date as lacking daily market prices, even though the default resolver selected it. Intraday/default and explicit daily behavior need one coherent contract.

### What is present, what is incomplete

Build is real: seven objectives, three return methods, stored IPS constraints, editable proposed weights, allocation comparison, historical modeling, diagnostics, and saved proposals. The successful default run changed modeled return from 20.4% to 21.5%, volatility from 16.5% to 15.8%, and displayed beta from 0.83 to 0.76. These are **model outputs for this run**, not forecasts or investment recommendations. Sharpe was unavailable. HHI worsened, and proposal compliance reported BREACH.

Quant is real: efficient frontier, CAPM/SML surface, correlation, rolling risk, distribution, and risk contribution. Its frontier is explicitly a **risky-sleeve comparison**, excluding cash and some IPS constraints; Build compares total capital. The proposed portfolio from Build is not automatically the highlighted frontier portfolio. This distinction must remain visible. The small frontier segment can reflect the actual feasible set; the supplied smooth broad curve is not a correctness target.

Risk has actual concentration, tail, and risk-contribution calculations, but does not implement the supplied risk brief/rolling comparison layout. Its event/data section is mostly cutoff/warning counts, and liquidity modeling explicitly remains unavailable. Portfolio Overview's brief is a deterministic daily PnL/benchmark paragraph, not a cited ongoing portfolio assessment.

Events have not simply vanished: they render in several places, but are repetitive or noisy, explanations are missing, and the portfolio feed fails. A same-day prior [ingestion check](../2026-10-07-live-ingestion-and-classification-check.md) records running workers, fetch allowances reached, disabled enrichment, and downloaded reports lacking retrieval chunks. Those earlier findings are useful context, **not fresh counts from this audit**. Running workers, stored PDFs, and generated section records do not establish usable intelligence.

## What to take from Rallies and the supplied images

The actual Rallies app differs from the supplied mockups. Rallies uses a narrow icon rail, white canvas, mostly sans-serif type, compact top controls, company-logo/quote chips, centered Chat, and a three-part Markets experience: navigation/list → Digest → Ask. Your images use a wider labeled rail, restrained serif display type, data tables/charts, and a brief rail. A deliberate combination is appropriate.

Observed Rallies Digest connects each short driver to security chips and a targeted question; upcoming events are inside the briefing. Chat places a restrained composer below a readable column and presents follow-ups after the answer. These are visible interaction patterns. Its public [product page](https://rallies.ai/) also describes portfolio-aware research, chat, discovery, and monitoring; that marketing does not independently establish its implementation internals or financial accuracy.

### Proposed visual system

- Canvas `#FFFFFF`; ink `#0B1628`; muted `#627087`; dividers `#E8EDF3`; positive `#00A879`; negative `#EB334A`. Blue `#006EFF` is reserved for links/selection, not decorative card accents.
- UI/body: existing Inter/system stack; restrained Georgia display face for major portfolio names and brief headlines only; tabular sans-serif numbers. Reduce portfolio titles to about 32–40px, with long names wrapping or shortening safely.
- Desktop labeled rail about 152–176px, collapsible to a compact icon rail; one stable order and brand. Compact 44–48px context toolbar; tabs immediately below the page identity. No duplicate eyebrow/title/subtitle/status stacks consuming the first 250–300px.
- Charts and tables own the main workspace; a 300–360px rail supplies evidence-backed briefs and contextual Ask. At narrower content widths, the rail becomes a drawer or lower section. Build's four panes must respond to available container width.
- Signature interaction: **event → affected company logos → selected portfolio exposure → evidence → Ask about this impact**. Animate loading/updates and navigation transitions only when they clarify state. Do not create perpetual moving tickers or random motion to suggest live data.

```text
stable rail | compact current context / market observation date / actions
            | portfolio or market tabs
            | principal chart + metrics + tables | cited brief / risks / Ask
```

### Page contracts to build toward

| Page | Principal content | Context rail / actions |
|---|---|---|
| Overview | Selected portfolio performance, dated market breadth, material changes | Market brief, top portfolio risks, upcoming verified events, contextual follow-ups |
| Markets | Complete-session index/breadth, searchable prices, movers, sectors, ranges | Pakistan-relevant market drivers, affected securities, dates, sources |
| Company | Logo/name/quote, price chart, validated fundamentals, valuation and cash-flow/liquidity ratios | Company Intelligence brief; separately selected Portfolio Relevance and Security Fit |
| Portfolio Overview | Ledger value/TWR, cash, holdings, daily contribution, benchmark | Portfolio brief, contributors/detractors, active risks, latest activity |
| Build | Current → controls → proposed, per-objective prerequisites, comparison | Binding constraints, rejected/unevaluated checks, tradeoffs, explanation of deltas |
| Quant | Active analysis with selectable comparison objects and clear units/basis | Observed rate, proxy, estimator/sample, missing prerequisites, export |
| Risk | Risk summary, trend, concentrations, tail, mandate checks | Prioritized risk brief and source-backed event exposure; no artificial all-clear |
| Research | Search/filter/date/source/entity controls and evidence rows | Selected evidence detail, exact highlights/citations, related company/events, Ask |
| Monitoring | Dated alert queue with severity/status/affected assets | Rules, last run and coverage, enabled/disabled state, evaluator failures |
| Assistant | Full readable conversation, streaming/stopping, saved chats | Compact scope chips, sources and useful follow-ups; diagnostics behind disclosure |
| Settings | Application, AI providers, notification settings | Portfolio mandate link; encrypted keys remain server-side and masked after save |

Ratios must be defined individually. Current/quick/cash ratios require their matching balance-sheet inputs; valuation needs eligible prices/share counts and compatible earnings periods. Financial and nonfinancial sectors require appropriate peer metrics. Each unavailable result needs a specific missing-input or eligibility reason. Never derive exact ratios from arbitrary RAG text.

Brief projections should share stored evidence and numerical contracts across page rails and Assistant. A portfolio risk item needs the selected portfolio and IPS version, observation dates, affected holdings and exposure denominator, direct/indirect relationship, impact mechanism, confidence, unknowns, and citations. A missing explanation should preserve the event and expose its incomplete state. Refresh facts/rules when their evidence changes; do not trigger an expensive full synthesis on every navigation.

## Incremental implementation sequence and acceptance

1. **Restore trustworthy reads.** Reconcile complete daily sessions with intraday overlay, canonical freshness, failing SQL queries, fact eligibility, and null compliance. Acceptance: the explicit and default market session agree on their documented basis; October 2 reproduces 467 company rows/37 sectors; partial October 7 coverage is labeled; failed compliance never says pass or zero breaches; concurrent portfolio requests do not trigger shared-memory errors.
2. **Connect existing capabilities.** Repair company ratio contracts and risk-free/proxy ingestion/selection; expose company synthesis state, portfolio event relevance, monitoring evaluation state, and optimizer post-check details. Acceptance: every absent metric names the missing prerequisite; invalid FFC rows cannot become ratio inputs; a violating saved proposal stays visibly review-required; rate metadata is sourced/effective-dated.
3. **Unify the shell and responsive layouts.** Adopt one visual token system and logo registry. Repair Build overlap before adding panels. Acceptance: 1280/1440/1600 desktop widths and a narrow viewport have no overlapping table/rail text; stable brand/navigation across all routes; charts and useful data appear in the first screen; missing history does not reserve a large empty canvas.
4. **Deliver shared market/portfolio/risk briefs.** Use ranked eligible events, compact numerical projections, supported portfolio exposure, source diversity, and verified upcoming events. Acceptance: Markets does not default to five copies of one topic when relevant evidence exists; a reader can follow every material statement to its evidence and understand why an event affects owned assets. Empty/synthesis-unavailable states are explicit.
5. **Finish research and Assistant workflows.** Evidence detail rail, company tabs, contextual Ask, full Chat, citations, follow-ups, and collapsed diagnostics. Acceptance: scope survives navigation; source links resolve correctly; stale evidence is labeled; fresh paraphrased prompts use appropriate data contracts; no unsupported advisory conclusion bypasses the evidence gate.

Targeted regressions should cover market-date coverage with two newer quotes, canonical versus legacy freshness, null/error compliance, financial unit/column/taxonomy eligibility, rate effective dating, and an optimizer result that fails a post-check. Live browser verification must exercise partial loading and failures as well as success. A cosmetic screenshot comparison alone is insufficient.

No new migration is proposed by this audit. Before implementation, use the existing [setup instructions](../../setup.md) and [Oracle runbook](../../oracle-deployment.md). Typical local checks are `cd apps/web && npm run typecheck`, `npm test`, and the API's documented targeted test command. Any schema change must name its migration and use the documented `alembic upgrade head` workflow; do not run a migration merely to apply a theme.

## Code map

- `apps/api/app/services/market_service.py`: default date, snapshot, rankings, sectors, legacy freshness.
- `apps/api/app/services/canonical_market_service.py`: selected price reads and price-history query.
- `apps/api/app/services/workstation_service.py`: Quant, compliance dependency, observed risk-free resolution, optimizer.
- `apps/api/app/services/context_consumer_service.py`: company-view adapter returning empty derived fundamentals.
- `apps/api/app/services/research_service.py`: legacy derived metrics and compatible periods.
- `apps/api/app/services/research_intelligence_service.py`, `api/routes/research_intelligence.py`: event selection, five-record feed, relevance.
- `apps/web/components/CompanyDigest.tsx`, `app/companies/[symbol]/page.tsx`: evidence dump, brief state, all-or-nothing company loading.
- `apps/web/components/WorkspacePage.tsx`: null compliance banner and remaining legacy Risk surface.
- `apps/web/components/workspace/useWorkspaceData.ts`: concurrent portfolio resources and aggregated errors.
- `apps/web/components/portfolio/BuildTab.tsx`, `portfolio/build/build.module.css`: actual Build controls, proposal save, responsive grid.
- `apps/web/components/portfolio/quant/*`: risky-sleeve assumptions and analysis charts.
- `apps/web/components/markets/*`, `overview/*`, `PortfolioWorkspace.tsx`, `AppShell.tsx`, `app/globals.css`: route-specific style drift, stale header/footer basis, logo behavior.
- `apps/web/components/AssistantWorkspace.tsx`, `AssistantChatMessage.tsx`: overlay/workspace, citations, diagnostics.
- `apps/web/app/settings/page.tsx`: global investment-setting controls conflicting with the portfolio IPS domain.

The sample images are layout references, not financial test data. Their Risk page shows PKR 62.4M as 1.3% beside a roughly PKR 4.5M portfolio; those numbers do not reconcile. Use real computed denominators, legitimate observation intervals, and backend-supported controls instead of copying illustrative figures or unsupported tabs.
