# Phase 8 dependency assessment

The supplied final revamp plan is the implementation specification. Work is read-only
with respect to portfolios, IPS, allocations, scenarios, ingestion, and trading.

| Boundary | Callers and contract | Replacement / regression boundary |
| --- | --- | --- |
| Assistant orchestration | HTTP message routes, persisted conversations and Phase 7 context receipts | Preserve response contract and ownership; durable runs wrap orchestration |
| Canonical context | Assistant, company intelligence, security fit, refresh services | Project only at model boundary; do not alter stored provenance |
| Reasoning graph | Assistant and offline fixtures | One bounded graph, discovery/reduction/deepening/synthesis/validation/repair |
| Provider adapters | Reasoning, key validation, research consumers | Keep positional chat compatibility; additive capabilities and usage metadata |
| Validation | Reasoning graph, Phase 8 fixtures | Local transport repair, scoped evidence and numerical references |
| Analytical services | Tool registry, portfolio and decision routes | Calculation-only recommendation verification; no proposal persistence |
| Diagnostics | Historical LLMInvocation rows | Preserve historical rows; independently committed execution attempts |

Incident regressions include 233 event subjects / 224 references, duplicate evidence,
malformed transport, unknown citations, budget exhaustion, and incomplete discovery.
No external calls or live database reseeding are part of validation.
