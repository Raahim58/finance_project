# Architecture

The workstation is a modular monolith: Next.js 16/React 19 calls a FastAPI application backed by SQLAlchemy 2 and Alembic. PostgreSQL with pgvector is the production target; SQLite is the deterministic local/test fallback.

```text
Next.js workstation
        |
FastAPI routes + shared ownership checks
        |
services: ledger | assumptions | allocation-state analytics | optimizer | compliance | research/RAG | scenarios | monitoring
        |
structured database queries + immutable source/document evidence
        |
typed tool registry -> bounded assistant orchestrator
```

## Data boundaries

Exact market prices, rankings, portfolio values, P&L, risk, optimizer weights, and scenarios come from structured rows and deterministic calculations. RAG is only for unstructured document text. A private document query always includes owner and optional portfolio scope; public documents are shared read-only.

Enabled ingestion follows `source -> immutable artifact -> versioned parser -> validation -> canonical observation/fact/event`. Conflicting observations are retained. A selected canonical observation is identified separately, with source priority and quality metadata. Development mock data is labeled and cannot create a synthetic live KSE-100 value.

Phase 7A adds a versioned, request-scoped Canonical Intelligence Context above
those stores. It deterministically assembles only the sections requested by Company
Intelligence or a portfolio-specific consumer. Company Intelligence cannot include
a portfolio or IPS; Portfolio Relevance uses exactly one selected, owned portfolio;
Security Fit additionally requires that portfolio's confirmed IPS. Exact values
remain structured queries and RAG remains bounded unstructured evidence. The
builder performs no writes, ingestion, or LLM calls.

Each section carries its own readiness, as-of value, authoritative freshness policy,
stable evidence references, and dependency hash. Soft provider failures degrade one
section; identity, scope, ownership, and Security Fit mandate failures abort. Full
contexts are temporary. Only compact receipts and durable structured deficiencies
may be persisted. A separate bridge deduplicates deficiencies and delegates worker
selection to an ingestion coordinator; it never exposes queues or providers to the
context caller. Linked work produces one rebuild after every job is terminal, or a
lazy rebuild when the consumer is no longer active.

The production coordinator links deficiencies to the existing five-minute market
scheduler ledger, Phase 2 history/report coverage and Celery tasks, macro-series
runs, and targeted evidence requests. PostgreSQL/SQLite conflict upserts make
deficiency and work deduplication atomic. The Phase 2 scheduler reconciles linked
terminal states, performs the single permitted active rebuild, persists a compact
receipt and notification outbox item, and marks inactive requests for lazy rebuild.
Section reuse checks cheap authoritative dependency versions before invoking the
section provider, so a cache hit avoids calculations and narrative retrieval rather
than merely comparing their outputs afterward.

Phase 7B makes Company Research and Assistant consumers of that same contract.
Company Research is company-only unless one portfolio is explicitly supplied; a
portfolio switch changes only the portfolio and IPS dependencies while stable
company evidence remains reusable. The authenticated overview response includes
the contract version, compact receipt, refresh identifier, and a temporary
compatibility projection for the existing Company page. That projection is derived
from canonical sections and does not call the legacy company assembler.

Assistant builds intent-scoped canonical sections before deterministic fallback or
LLM synthesis. Security Fit requires one owned portfolio and its selected confirmed
IPS, always includes bounded company RAG and material normalized events, and uses
the normal safe planning loop. Application-level risk tolerance, horizon, and
sector preferences are excluded from intelligence; user preferences may still
choose an LLM provider. Canonical evidence IDs form the synthesis allowlist and the
saved Assistant message references the exact compact receipt. A completed refresh
adds a linked deterministic follow-up instead of editing the original answer.

Consumer requests persist reconstructable ingestion coverage and refresh ledgers
without publishing Celery work inline. The existing Phase 2, macro, evidence, and
live-market schedulers remain responsible for publication and execution. This keeps
authenticated requests bounded when Redis or a worker is unavailable.

Phase 7C retires the legacy security-context assembler, GET route, tool registration,
frontend contract, and response shape. Canonical Intelligence Context is now the sole
shared intelligence assembly contract for Company Research and Assistant. Candidate
evaluation and proposal persistence remain separate deterministic workflows; their
POST routes, portfolio comparisons, scenarios, IPS checks, and audit behavior are
unchanged.

## Phase 8 reasoning boundary

Phase 8 is implemented as a stateless Assistant reasoning module. Each execution
receives the current request, the globally selected active user-owned portfolio as the
fallback portfolio context, any explicitly selected security, bounded conversation
history, and a freshly assembled Canonical Intelligence Context. The selected
portfolio's identifier and name are supplied to the model. Market-wide describes the
candidate security universe, not the absence of portfolio context. Free-form text is
not allowed to silently switch the portfolio; an explicitly selected portfolio is
resolved and ownership-checked by the server, otherwise the global selection is used.

`ReasoningEngine` remains the application-owned interface. Its initial orchestration
implementation uses a LangGraph `StateGraph`, while canonical request, context,
evidence, recommendation, and validation contracts remain framework-independent.
Phase 8 compiles the graph without a persistent checkpointer and does not adopt the
LangChain agent, retrieval, memory, or tool abstractions. Existing Conversation,
AssistantMessage, context receipt, evidence, and trace records remain authoritative.
PostgreSQL graph checkpoints and `conversation.id` thread identity are deferred until
Phase 11 or future resumable analytical-tool execution creates a real pause/resume
requirement.

The current Phase 8 module reads and recommends but does not invoke portfolio tools,
optimizers, screeners, or scenario engines and does not save proposals or modify
portfolio or IPS state. It may interpret existing deterministic analysis results.
Read-only analytical tool execution is a future extension behind the same reasoning
boundary.

The model writes the user-facing answer once. Its provider response contains that
natural-language answer plus compact fields such as advisory conclusion, horizon, and
confidence, with inline references to allowed evidence IDs. The API displays the
model's answer without reconstructing or duplicating its prose. Explicit conclusions
may be Buy/Add, Hold, Reduce, Avoid, or Insufficient Evidence and include the applicable
horizon, thesis, portfolio/IPS fit where applicable, catalysts, risks, invalidation
conditions, confidence, missing evidence, and citations.

Holding analysis and user-named comparisons normally perform one model synthesis call.
Market-wide recommendations are the deliberate exception. The complete eligible active
universe is partitioned by authoritative available security classification. The current
classification authority is the PSX sector observed from the PSX symbol universe; no
sub-industry is inferred from names or narrative text. A separately sourced sub-industry
may be used only after its provider and provenance are verified. Unclassified securities
remain in an explicit unclassified packet and are never silently omitted. Each group
receives compact, consistent-period structured evidence and group-appropriate metrics;
securities are assessed primarily against their peers rather than through one raw
cross-sector ranking. LangGraph maps every complete sector packet through parallel
discovery calls, keeping classification boundaries and coverage accounting explicit
regardless of total context size. Discovery selects bounded candidates within each sector without issuing an
advisory conclusion. The application then builds deep Canonical Intelligence Context for
the sector candidates, and a final model call performs portfolio/IPS-aware cross-sector
comparison and writes the recommendation. This is read-only context expansion, not
optimizer or scenario execution. One additional model call is permitted only as the
single constrained repair attempt after a mechanically invalid response. Phase 8 has no
critic or semantic-judge model call.

Blocking validation is restricted to mechanically provable invariants: response
schema and enums; equality of returned instrument, portfolio, and scope identifiers
with trusted request/context values; prior ownership resolution; evidence-ID
membership in the canonical allowlist; exact numerical agreement with authoritative
structured evidence and units; presence of a horizon source; and required disclosure
of freshness states used by the answer. The validator never decides whether evidence
is persuasive, whether sources are materially contradictory, whether a risk changes
the thesis, which advisory conclusion is justified, or whether an outside security is
a meaningful alternative. Those are semantic judgments made by the model and measured
through evaluations.

Semantic checks begin in non-blocking shadow mode. A labeled evaluation set measures
false abstention, unsupported recommendations, incorrect portfolio scope, citation
misuse, and conclusion consistency. Only checks demonstrated to be objective
invariants may become blocking. Missing optional sections do not accumulate into a
generic penalty score. A structural failure may receive one constrained repair attempt;
the validator may accept the model's conclusion or reject the structurally invalid
response, but it never rewrites Buy as Hold or otherwise substitutes its own financial
judgment.

Provider adapters capture native input/output token counts when the provider returns
them. `ReasoningEngine` accumulates those counts across sector discovery, candidate
reduction, synthesis, and the optional repair call; the Assistant displays input,
output, total, and model-call counts. Counts are labeled unavailable rather than
estimated when a provider does not report usage. Provider and graph failures retain a
sanitized reason in uncertainty and trace metadata instead of becoming an unexplained
fallback.

If the configured provider is unavailable or the response remains structurally invalid
after the single repair attempt, the API returns the available deterministic factual
summary and evidence cards without an advisory conclusion. The result is labeled
Recommendation Synthesis Unavailable rather than Insufficient Evidence because the
failure belongs to model synthesis, not necessarily to the underlying evidence. A
deterministic fallback never invents Buy/Add, Hold, Reduce, or Avoid.

Global Evidence v1 is deliberately staged. Pass 0 established persistence and
contracts. Pass 1 adds the first synchronous vertical slice: configured discovery
through RSS/Atom, sitemaps, GDELT, verified listing pages, and the observed PSX
announcements POST contract; JSON-LD-first HTML extraction; deterministic relevance,
fingerprinting, bounded deduplication, event clustering, evidence-role selection;
and indexing only selected evidence through the existing document pipeline. Full
article text remains ephemeral unless selected. Selected raw responses are gzip
compressed in the artifact store, while rejected and duplicate candidates retain
metadata and fingerprints only.

Pass 1 performs no import-time I/O and retains its bounded manual runner. Pass 2
adds evidence-only discovery, fetch, parse, PDF, index, and historical Celery queues;
a dedicated Postgres-led scheduler; bounded leases/backpressure/retries and source
circuits; candidate/spool retention; deep-company historical requests; operational
health; and ownership-scoped targeted refresh requests.

Pass 3 adds only conservative historical hydration. Durable presets cover 12
months of PSX announcement metadata, 12 months of existing-source evidence for
Deep companies, and 90 days of configured news discovery. Each execution advances
one bounded Postgres cursor, yields whenever durable live work exists, and enforces
candidate, fetch, and byte budgets at the worker boundary. Budget increases require
seven continuous healthy days. Source breadth, new publisher adapters, and
Playwright remain later-pass work. Product Phases 4–6 retrieval, entity/event
intelligence, and final assistant reasoning are not pulled into ingestion.

## Portfolio state

Transactions are the audit ledger. Buys, sells, deposits, withdrawals, fees, taxes, dividends, opening balances, adjustments, and reversals drive cash and positions. Holdings are a current projection, not an independent source of historical truth. Legacy holdings receive a dated migration baseline and pre-baseline history is marked incomplete.

Investor profiles and portfolio IPS records use editable drafts and immutable confirmed versions. Monitoring, compliance, and optimization only use a selected confirmed IPS. Allocation sets represent sandbox, target, or immutable optimized proposals; none mutate holdings.

## Quant and scenarios

Pure modules under `app/domain/quant` implement returns, covariance/correlation, regression, drawdown, risk/performance metrics, VaR/ES, and risk contributions. CVXPY runs convex optimizers and SciPy runs deterministic multi-start risk parity/budget methods. Inputs, cutoff, estimator, solver, diagnostics, and result summaries are persisted. Unsupported IPS constraints are reported instead of silently removed.

Scenario arithmetic is deterministic. Direct instrument shocks override mappings; sector and factor mappings apply only when there is no direct shock, preventing double counting. Historical replay labels current-holdings replay as counterfactual.

The presentation boundary exposes chart-ready capital-market assumptions,
efficient-frontier markers, CAPM/SML points, dated rolling risk, empirical return
distributions, capital-versus-risk contribution, and current-versus-proposed
comparisons. The same covariance and expected-return assumptions are disclosed on
both sides of a comparison. Cash has zero modeled covariance and only receives an
expected return when an observed effective-dated risk-free series is available.

## Assistant and monitoring

`app/tools` is the only assistant execution boundary. Each definition declares version, validated input, scope, read-only/confirmation policy, timeout, cost class, and handler. The model receives no SQL, filesystem, dynamic import, arbitrary network, credential, or trade-execution capability.

The orchestrator bounds iterations, retrieved chunks, and request time; gathers ownership-scoped calculations and citations; and falls back to an evidence-based deterministic answer when a provider response is ungrounded. Monitoring jobs persist runs and deduplicate alerts by rule/window. Recommendations require a user decision and never auto-apply.

## Scheduling and ingestion workers

The scheduler keeps the efficient broad DPS current-session refresh in-process. Celery/Redis coordinate four expensive queues: one company DPS page, one symbol-month of DPS history, one financial catalogue/PDF download, and one PDF extraction per task. Network workers target 16–24 concurrent tasks; PDF extraction targets 2–4. Postgres `ingestion_coverage` rows are the durable work ledger, so Redis is never the source of completeness and lost messages can be reconstructed.

The active broad universe is synchronized from observed DPS ordinary-equity identities. Standardized DPS facts are stored separately as `standardized_secondary`; official report `FinancialFact` rows remain issuer-report facts with document/page/row/method provenance. Screening snapshots are deterministic, persisted, sector-aware, and keep completeness separate from performance. Broker automation, trade execution, derivatives, and external MCP runtime remain absent.

Global Evidence workers use separate pools from Phase 2. Redis messages contain only
IDs and approximate priority; Postgres source/candidate/request state is the durable
ledger. A shared bounded spool carries temporary bodies between stages and selected
content moves to the artifact/document stores. The evidence scheduler reconstructs
expired leases without producing any Phase 2 task.
