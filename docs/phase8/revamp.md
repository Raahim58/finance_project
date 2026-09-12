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
