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
