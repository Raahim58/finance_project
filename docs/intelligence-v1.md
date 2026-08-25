# Intelligence Layer V1

## Architecture map

Intelligence V1 is orchestration, not a new source of portfolio truth.

| Decision input/output | Existing authority reused | V1 composition |
|---|---|---|
| Price, return, sector, freshness | Canonical Market services and selected observations | Security context and aligned candidate universe |
| Exact fundamentals | `FinancialFact` | Observed-fact section with document provenance |
| Filings, news, events | Documents/RAG and Event records | Evidence section; RAG is never used for exact numbers |
| Macro/regime | `MacroObservation` and `regime_service` | Regime context and stress-template routing |
| Holdings, cash, portfolio value | Ledger and portfolio summary | Read-only current weights; candidate actions never write the ledger |
| Expected return, covariance, risk, optimizer | Existing quant domain and comparison service | Current/candidate universe comparison and optional minimum-variance sizing |
| Stress | Existing scenario templates and shock resolver | Same scenarios evaluated against current and proposed weights |
| Constraints | Confirmed IPS and compliance service | Current, proposed, and stressed compliance |
| Saved decision | Existing sandbox `AllocationSet` and audit event | Reviewable proposal with the evaluation assumptions and stress package |
| Explanation | Canonical Intelligence Context and grounding guard | Security + portfolio context; deterministic numerical evidence remains authoritative |

## API flow

- `GET /companies/{instrument_id}/overview?portfolio_id=...` returns the versioned Canonical Intelligence Context, compact receipt, portfolio relevance for exactly the selected portfolio, and explicit section-level missing-data states.
- `POST /intelligence/securities/{symbol}/evaluate` evaluates `add`, `reduce`, or `remove` using a manual target, or optimizer sizing for an add. It returns current/proposed metrics, risk contributions, compliance, stress results, and deterministic trade-offs. It does not mutate holdings or transactions.
- `POST /intelligence/securities/{symbol}/proposals` repeats the authoritative evaluation and saves the proposed weights as an existing `sandbox` allocation. The existing proposal audit event is recorded.
- Assistant requests may include `instrument_id` and `portfolio_id`. Assistant orchestration consumes the same versioned Canonical Intelligence Context for deterministic or LLM-backed explanations; Security Fit requires the selected portfolio and its confirmed IPS.

No database migration is required because V1 deliberately reuses `AllocationSet` for proposals and existing audit infrastructure.

## Assumptions and gaps

- Candidate comparison requires at least 31 dates aligned across current holdings and the candidate. Missing history produces an explicit unavailable response; no synthetic substitute is generated.
- Optimizer sizing uses the existing minimum-variance solver, holds the current cash weight constant, and applies configured maximum instrument and sector bounds. It is a modeling choice, not an autonomous recommendation.
- Stress results are first-order template shocks. A template's documented fallback is used only where that existing template provides one; otherwise an unmapped security receives a zero shock.
- Scenario evaluation in V1 is intentionally ephemeral. Only a saved proposal persists its stress package; it does not create ordinary `ScenarioRun` records for the actual portfolio.
- Security-specific deterministic explanations cover ownership, IPS headroom, and aligned correlation. Documentary contradiction analysis still depends on relevant ingested RAG evidence.
- The current repository has no certified complete corporate-action/total-return history, full institutional financial normalization, or broad-market opportunity ranking. Those remain outside V1.
