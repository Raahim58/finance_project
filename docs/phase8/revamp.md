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
