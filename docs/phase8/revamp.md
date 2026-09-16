# Phase 8 revamp

The final Phase 8 revamp permits verified, read-only allocation recommendations and
funded switches. The model proposes gross purchases and specific funding sales.
Deterministic services derive provisional quantities from canonical database prices,
apply stored lot sizes when present, calculate cash and resulting weights, compare
available portfolio analytics, and enforce the confirmed IPS. Brokerage and tax costs
remain separate and unknown. No Phase 8 analysis creates trades, holdings, transactions,
saved allocations, optimizer proposals, scenarios, or ingestion work.

Model input uses one compact projection. Repeated objects are interned by stable content
hash; provenance stays in canonical records while model-visible facts retain stable
references. History is token-bounded and labeled as non-current evidence. Documents and
prior messages cannot change scope, permissions, portfolio identity, or the IPS.

Provider attempts are recorded before sending and completed independently of answer
persistence. Requests are deduplicated by `(user_id, client_request_id)` and conflicting
reuse is rejected. The browser stores the active execution ID in session storage, polls
the owner-scoped run endpoint, and acknowledges receipt separately from persistence.

Diagnostic exports use an explicit structural allowlist. Encrypted captured prompts and
responses are internal-only and available solely for offline replay through mock
providers. Ordinary inspection and CLI output never expose those payloads.

Assumptions and limits:

- Whole-share sizing is provisional when instrument metadata has no lot size.
- Affordability is gross because brokerage, fees, taxes, and tax lots are unavailable.
- A missing confirmed IPS or unavailable binding check prevents an actionable allocation.
- Existing breaches are reported separately; improvement does not imply resolution.
- Mock market data remains development-only and is labeled by its stored source.
- Offline fixtures validate mechanics, not live-model quality, billing, or latency.
- Broad cleanup and Phase 11 chat/history/drawer work remain deferred.

## Phase 1 acceptance report

Phase 1 replaces the model-visible tool surface with explicit read operations. Tool
argument JSON Schema is generated from the registered Pydantic input model. The shared
result envelope reports `status`, typed `data`, server-owned `sources`, and pagination
`coverage`; coverage also carries measured elapsed milliseconds and clearly labelled
byte/token estimates. `research.refresh_company` is no longer registered and therefore
cannot be selected or dispatched by the Assistant.

The company tool accepts only explicit company-facts, market-risk, sector, macro, and
event sections and calls the read-only canonical context builder directly. It does not
use the context consumer that records deficiencies or schedules refreshes. New tools
provide stable active-universe pagination, read-only allocation verification, grouped
document discovery, complete physical-page or matched-chunk reads, actual retained-PDF
bookmarks, and retained-PDF page images. Explicit document reads repeat the ownership
predicate; model arguments never contain a file path or arbitrary source URL.

The MEBL oversized-input acceptance case is explicitly a reconstruction because the
exact historical provider payload was not retained. Its production-shaped nested event
subjects and source records serialize to 64,402 and 67,557 bytes respectively (233
subjects and 224 sources); company and fixture metadata add 124 bytes. This isolates the
dominant components instead of treating record counts as a size proxy.

Focused acceptance command:

```bash
cd apps/api
.venv/bin/python -m pytest app/tests/test_phase8_phase1_read_tools.py -q
```

The cases compare company periods, decimal values, units, source conflicts, current
prices, pagination counts, document ownership, and complete stored page text against
independent database reads. They include a private document, adjacent pages, an
extraction gap, duplicate reads, a missing PDF original, retained-PDF bookmarks and PNG
rendering, and verify that read operations do not add transactions, allocations,
documents, or refresh requests.

Remaining work is intentionally outside Phase 1: provider-native tool turns, the single
model-directed loop, durable transcript continuation, citation-marker resolution, and
streaming belong to Phases 2 and 3. Live-model answer quality remains a handoff gate and
is not claimed by these offline checks.

## Phase 2 acceptance report

Phase 2 replaces the Assistant's fixed planning/classification/recovery graph with one
explicit provider loop. Initial input contains the question, bounded conversation
history, server-resolved portfolio/instrument identity, and the current read-tool
catalog. It performs no evidence prefetch and no paid formatting-repair call.

Anthropic and Gemini adapters now transport typed text, tool-call, tool-result, and image
blocks in their native request formats. Tool-only and parallel calls remain valid and
IDs remain associated with their results. These contracts were checked against the official
[Anthropic tool-use documentation](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use)
and [Gemini Interactions documentation](https://ai.google.dev/gemini-api/docs/interactions-overview).

Provider turns and tool-result turns are encrypted and checkpointed separately. Resume
rechecks user, conversation, and portfolio ownership, keeps the originally selected
provider/model, and reuses byte-identical completed attempts. An uncertain external
provider request fails explicitly instead of being replayed and possibly charged twice.
Independent calls run concurrently with a maximum
of four workers; every database worker creates its own session. PostgreSQL workers set a
transaction-local statement timeout, while the orchestration timeout ignores any late
worker result.

Final provider prose is accepted directly. Valid raw or fenced legacy JSON is locally
unwrapped only when it contains a string `answer`. Citation markers resolve solely from
sources delivered during that execution; unknown and absent citations are explicit, and
the result always states that semantic verification was not performed. Structured
allocation quantities still come from the deterministic verifier and never mutate
financial state.

Removed paths:

- `app/reasoning/engine.py`, `planning.py`, `validation.py`, `contracts.py`,
  `peer_groups.py`, and `grounding.py`
- superseded deterministic Assistant orchestrator/graph tests; shared allocation,
  projection, research, portfolio, market, and compliance services remain

Focused offline acceptance command:

```bash
cd apps/api
.venv/bin/pytest app/tests/test_phase8_phase2_tool_loop.py \
  app/tests/test_llm_provider_usage.py app/tests/test_phase8_revamp.py \
  app/tests/test_tool_registry.py -q
```

The scripted cases cross real provider adapters, the allowlisted registry, database
services, encrypted attempts/checkpoints, and final persistence. They cover ambiguous
company discovery, two-company/portfolio comparison, universe continuation, missing
data, malformed and forbidden calls, duplicate IDs, ordered parallel results,
tool-only turns, allocation sizing, overselling, IPS breaches, truncation, provider
errors, restart, and checkpoint/final-message persistence failures. Fixtures seed their
own database setup, but Assistant-dispatched tools perform no ingestion, broker, or
financial-write operation; the suite performs no network or paid model call.

Observed Phase 2 boundary results on 2026-09-13:

- focused native-loop/provider/registry suite: 38 passed in 7.67 seconds
- complete backend suite after the final relevant change: 358 passed in 152.77 seconds
- fresh SQLite migration: upgraded from base through `0029_assistant_tool_loop` in
  2.93 seconds; `assistant_executions.transcript_encrypted` was present and nullable
- Python bytecode compilation and `git diff --check`: passed
- Ruff was not installed in the project virtual environment, so no Ruff result is
  claimed; the repository test suite and syntax/diff checks are the recorded gates

Phase 3 streaming and its browser delivery checks remain unimplemented. Live-model
selection and answer quality also remain an explicit later gate; Phase 2 makes no live
quality claim.

## Gemini Interactions improvement

New Gemini Assistant executions use the stateful Interactions API. The initial request
sends the question and bounded prior conversation. Each continuation sends
`previous_interaction_id` and only newly completed function results; tools and system
instructions are re-supplied as required by the API. Interaction IDs and completed
results are encrypted in the durable checkpoint before the loop advances. Missing or
expired remote state produces an explicit terminal error and is never silently replayed.

Built-in Google Search and URL Context are disabled for every Assistant request because
model support does not establish quota for the configured Google project. External
coverage is reported unavailable instead of causing the whole model request to fail.
Any future enablement must be quota-aware and explicitly scoped to a request. Exact
prices, portfolio values, allocation math, and compliance remain backend calculations
over stored database values.

Research facts and events can be selected by section, exact period range, cursor, and
page size. Responses preserve requested records and continuation metadata; the server
removes duplicated serialization but does not invent a document summary. The existing
200,000 cumulative-input safeguard remains based on the provider's retained logical
context. Diagnostics separately report transmitted bytes and provider-reported input,
cached input, output, and reasoning tokens, and reconcile conservative reservations
when provider usage is available.

No schema migration is required for this improvement: interaction state fits the
encrypted transcript checkpoint introduced by `0029_assistant_tool_loop`. Native answer
streaming remains the separate Phase 3 deliverable. Offline checks do not establish
live-model answer quality; the OGDC price, MEBL portfolio-fit, and recent-event prompts
remain user-run live acceptance checks.

## Focused Assistant reliability correction (baseline d99b466)

The existing native loop and polling delivery remain in use. Tools normalize dates to
ISO strings and Decimals to exact strings before evidence registration. Unsupported
JSON values fail explicitly. Final serialization and allocation rendering have separate
`response_serialization_failed` and `response_rendering_failed` codes; database failures
retain `response_persistence_failed`. Diagnostics retain code, exception type and code
location, without exception messages or financial payloads.

Allocation envelopes remain compact for the provider and expand for server rendering.
The latest verification attempt replaces prior results, including unavailable attempts.
`synthesis.allocation_check` contains typed server rows for changed and unchanged holdings
and cash. Current/proposed capital weights are fractions of total capital; risky-sleeve
weights and percentage risk contributions are different metrics. The browser preserves
answer line breaks and displays verification, price freshness and modeled-goal outcomes
separately. Citation resolution checks reference identity, not whether prose is true.

The model receives holding instrument IDs, the selected IPS mandate and citable internal
portfolio/calculation references. It formulates provisional gross purchases and funding
sales itself when evidence permits. `allocation.verify` calculates quantities, cash,
weights, existing before/after metrics and compliance; no additional arithmetic,
comparison or optimizer tool is exposed. Its `accepted` flag means arithmetic/compliance
acceptance. Freshness readiness, modeled return versus required return and optimality
remain explicit separate meanings. Modeled return is an estimate, never a guaranteed
return or an IPS forecast. Freshness reuses trading sessions and source SLA policy.
Shariah metadata aliases must agree; conflicting values are unknown.

Assistant analytical reads use `persist=False`/`persist_analysis=False`. Matching existing
`AnalysisRun` results are reused before ledger-performance and covariance/risk work. The `quant-v2` dependency
fingerprint covers stored holdings/cash, full selected price observations and ledger/performance inputs,
IPS, benchmark observations, risk-free inputs and parameters. Older fingerprints miss
safely and calculate in memory. Other application callers retain analytical persistence.
No migrations or new cache storage are required.

`market.overview` selects `snapshot`, `gainers`, `losers`, `volume_leaders`, and/or `sectors`.
It defaults to snapshot only; rankings default to 10 and are capped at 50. Each section
reports available stored coverage and dates; missing snapshot data does not hide rankings.
`market.universe` defaults to identity/classification only and optionally selects stored
screening fields (`score`, `sector_percentile`, `completeness`, `screenable`, `growth_flag`,
`income_growth`, `pat_growth`, `eps_growth`, `net_margin`, `liquidity`). Snapshot reads are
batched per page and missing values/unclassified securities remain visible. Screening
percentiles compare sector peers, not unrelated business models. Company sector evidence
returns the selected sector by default; `sector_comparison_limit` explicitly requests up
to 20 extra sector rows. Events apply offsets once and expose continuation correctly.

Budgets remain 12 backend calls and 18 cost units, with the existing cumulative input
safeguard and history limits. Catalog descriptions disclose costs; continuations disclose
remaining allowances outside citation evidence. Allocation work is instructed to preserve
three units for verification. This guides model selection without promising live model
quality or adding routing/model repair calls.

### Offline checks and local recovery

Run the boundary once against an isolated database; the test fixtures drop/create tables:

```bash
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash \
  apps/api/.venv/bin/python -m pytest apps/api/app/tests -q
cd apps/web
npm test
npm run typecheck
npm run build
```

A checkpointed final provider answer can be finalized locally without another paid turn.
For a failed serialization/rendering/persistence execution, run this server-side recovery
from `apps/api` with the application's normal server configuration. Use the owning user ID
and exact failed execution ID; the helper refuses uncertain attempts and non-final turns:

```bash
python - <<'PY'
from app.db.session import SessionLocal
from app.services.assistant_execution import queue_finalization_recovery
with SessionLocal() as db:
    queue_finalization_recovery(db, 'OWNING_USER_ID', 'FAILED_EXECUTION_ID')
PY
```

The existing API maintenance loop schedules the queued execution. Expired provider-work
deadlines do not block purely local finalization. No external attempt is scheduled during
this recovery. Diagnostics expose safe failure locations in the execution's stage metadata.

### Prepared live benchmark — NOT EXECUTED

Capture expected facts in a read-only database snapshot immediately before any separately
authorized live run; retain source/date/missing states, not stale facts copied from a prior
answer. Store expected facts with run metadata and compare completed answers against that
snapshot. No benchmark model request is part of this correction.

| Request | Expected database facts / checks | Efficient first reads |
| --- | --- | --- |
| Latest MEBL price | Selected canonical latest close, currency, trade date and provenance; missing if absent | `market.series`, limit 1 |
| Compare MEBL and HBL | Only requested companies, consistent selected periods/units and sourced sectors/facts; disclose unavailable periods | Requested company sections |
| Analyze MEBL and recommend verified portfolio weights | Stored holdings/cash and confirmed IPS; verifier's quantities, gross amounts, unchanged holdings/cash and capital weights; independent readiness/goal results | Company evidence, summary, IPS, then verify |
| What led the market? | Database gainers/volume leaders/sector statistics for the effective date; record ranking coverage independently of snapshot availability | One selected `market.overview` |
| Broad discovery | Active stored universe, sourced classifications, stored selected screening fields and all missing values across stable pages; no final recommendation during discovery | Paginated screening universe, bounded deeper evidence |
| Missing evidence | Actual absent/stale company, mandate, price or external coverage; no invented financial facts or verified allocation | Relevant smallest read |

For each case record: request completion, factual accuracy against expected facts,
verification use for proposals, capital-weight agreement with server output (tolerance
only for display rounding), backend reads, provider calls, reported input/output/cached/
reasoning tokens, transmitted bytes and latency. A pass requires completed delivery,
correct sourced facts or explicit gaps, and server agreement for any proposed allocation.
Optimization or guaranteed goal attainment is not a criterion. Scripted acceptance tests
prove contracts and offline flow; this unexecuted benchmark is the later model-quality gate.
Streaming, external search, ingestion changes, trades, new optimizers and candidate-scope
contract changes remain deferred.

Read-only public database baseline captured on 2026-09-16 at 15:21 UTC (the model
benchmark remains unexecuted):

| Stored fact | Expected value |
| --- | --- |
| Latest stored MEBL close | PKR 587.90, 2026-08-12, source `dps` |
| Latest stored HBL close | PKR 334.31, 2026-08-12, source `dps` |
| Snapshot for latest stored market date | Missing |
| Top stored gainers for 2026-08-12 | IDEAL close 49.13 / volume 5,534; GAMON close 28.25 / volume 873,125; LEUL close 49.58 / volume 103,987 |
| Stored sector rows for that date | 47 |
| Active instrument records / screening snapshot records | 740 / 740 (instrument count is not a certification of eligible-universe coverage) |

These are dated stored facts, not current verified market prices. An answer against this
baseline must disclose the August cutoff and insufficient price freshness for an
actionable allocation. The missing snapshot must leave available rankings usable.
Refresh the expected-fact snapshot before a later authorized live benchmark. Private
portfolio/IPS values are deliberately excluded from this public documentation and must
be captured server-side for the owning benchmark portfolio. The offline accepted-flow
fixture records one held MEBL share, PKR 10,000 cash and a PKR 1,000 gross buy proposal;
its exact expected quantities/weights come from the stored fixture price and verifier.

### Completion evidence for this correction

The complete backend suite ran once on isolated SQLite: 376 passed and two initial
failures in 198.46 seconds. The allowance placement and workstation alignment-cache
regressions were corrected; the affected native-loop/read-tool/registry/revamp tests
and alignment-cache test then passed (54 tests, 109.56 seconds). Additional audit cases
verified missing snapshot with retained rankings, incomplete valuation, unavailable
prices and Gemini's delivered allowance; the sector-limit cache correction passed its
specific database acceptance test. Final cache checks passed (2 tests, 6.82 seconds),
including skipping ledger-performance work on a saved hit. Completed-answer recovery
passed with an expired provider-work deadline and no additional provider call. The
internal tool-failure diagnostic test passed with safe type/location metadata.

Frontend boundary: 7 files / 20 tests passed, typecheck passed, and production build
passed. The Assistant's final status-label correction passed its focused 6-test browser
component check and typecheck. `git diff --check` passed. No full backend rerun, live
model benchmark, external search, streaming, migration or application financial write
was performed by these checks. The public benchmark facts were collected in a read-only
transaction, separately from destructive isolated test fixtures.

| Plan item | Current implementation / acceptance evidence |
| --- | --- |
| A–B | Strict normalized JSON; handled final serialization; expanded latest allocation result; timestamp persistence and compact restart tests |
| C–D | Batched holding IDs; selected mandate; internal citable calculation/price metadata; database fidelity and no-write tests |
| E | Delivered system allowance for both providers; catalog costs; proposal/verification responsibility; 15+3-unit representative budget test |
| F | Shared source/session freshness and Shariah accessor; arithmetic/IPS/freshness/goal checks; stale/shortfall/missing IPS/valuation/price tests |
| G | Versioned ledger/price/IPS/benchmark/rate/parameter dependencies; saved lookup before performance/risk work; no-write and invalidation tests |
| H–I | One selectable database market tool; optional batched screening; selected-sector default and keyed comparison limit; three-page events and independent price ranking assertions |
| J | Typed server allocation checks/rows; historical compatibility; native table and separate labels; line preservation and citation fallback component tests |
| K | Safe stage code/type/location; explicit owned local recovery of checkpointed final answers; no uncertain replay or formatting-repair call |
