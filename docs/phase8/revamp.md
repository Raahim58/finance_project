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
blocks in their native request formats. Tool-only and parallel calls remain valid, IDs
remain associated with their results, and Gemini provider parts preserve opaque thought
signatures. These contracts were checked against the official
[Anthropic tool-use documentation](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use)
and [Gemini function-calling documentation](https://ai.google.dev/gemini-api/docs/function-calling).

Provider turns and tool-result turns are encrypted and checkpointed separately. Resume
rechecks user, conversation, and portfolio ownership, keeps the originally selected
provider/model, reuses byte-identical completed attempts, and applies the existing
uncertain-paid-attempt retry policy. Independent calls run concurrently with a maximum
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
