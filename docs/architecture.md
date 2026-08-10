# Architecture

The workstation is a modular monolith: Next.js 16/React 19 calls a FastAPI application backed by SQLAlchemy 2 and Alembic. PostgreSQL with pgvector is the production target; SQLite is the deterministic local/test fallback.

```text
Next.js workstation
        |
FastAPI routes + shared ownership checks
        |
services: ledger | quant | optimizer | research/RAG | scenarios | monitoring
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

## Assistant and monitoring

`app/tools` is the only assistant execution boundary. Each definition declares version, validated input, scope, read-only/confirmation policy, timeout, cost class, and handler. The model receives no SQL, filesystem, dynamic import, arbitrary network, credential, or trade-execution capability.

The orchestrator bounds iterations, retrieved chunks, and request time; gathers ownership-scoped calculations and citations; and falls back to an evidence-based deterministic answer when a provider response is ungrounded. Monitoring jobs persist runs and deduplicate alerts by rule/window. Recommendations require a user decision and never auto-apply.

## Scheduling and future boundaries

The current in-process scheduler invokes ingestion and monitoring services using stable run keys. Redis may later improve caching/locking but is not a correctness dependency. The service/tool interfaces can later move to workers or expose selected read-only tools over MCP without changing finance logic. Broker automation, trade execution, derivatives, and external MCP runtime are intentionally absent.
