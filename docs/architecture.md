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
