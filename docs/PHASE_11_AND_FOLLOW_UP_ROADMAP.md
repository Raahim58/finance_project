# Phase 11 — Persistent streaming Assistant

Status: implementation authorized. On 2026-10-03 the user additionally authorized commits, deployment, worker starts and live-model calls at the relevant implementation stages. Start with mocked verification; use live calls only for bounded acceptance checks. Ingestion activation remains in the ordered follow-up after the Oracle audit.

## Goal and locked behavior

Build a normal chatbot accessible from every authenticated page. Replace the standalone Assistant screen only after the chatbot works. Phase 9–10 fixes, ingestion, broader data coverage and the later UI overhaul remain deferred.

- Floating button opens a drawer; desktop supports expansion and mobile uses the available screen.
- Normal user/assistant messages, Markdown, inline citations, source links and essential missing-data warnings.
- New chat, saved conversation history, cursor pagination and switching chats.
- Navigation, drawer closure and conversation switching never cancel generation.
- Company/portfolio context follows the current page for the next submitted message. Display it above the composer and snapshot it at submission. Earlier messages retain their original context.
- Portfolio pages supply their portfolio; elsewhere use the selected default portfolio. Never select an arbitrary portfolio.
- Drafts belong to conversations and survive navigation.
- One active generation per conversation. Other conversations may submit and wait for the provider slot.
- Only explicit Stop generating cancels. Opening chats, reading, scrolling and viewing sources require no model calls.
- Existing Assistant links open the drawer and prefill without submitting. `/assistant` is a compatibility redirect, never another chat screen.
- No normal/deep classifier or budget-expansion tool.

## Token policies and memory

These are application ceilings, never target consumption. Server configuration explicitly selects a trial; snapshot version and limits into every accepted execution. Trial 2 never activates automatically and has no debugging control in chat.

| Setting | Trial 1 (default) | Trial 2 (inactive alternative) |
|---|---:|---:|
| Thinking for chat | Enabled | Enabled |
| Input per provider call, everything serialized | 48,000 estimated tokens | 96,000 estimated tokens |
| Output per provider call, reasoning included | 8,192 tokens | 8,192 tokens |
| Provider calls per question | 6 | 6 |
| Cumulative input per question | 180,000 tokens | 180,000 tokens |
| Cumulative output per question | 24,000 tokens | 24,000 tokens |
| History before compaction | 24,000 actual estimated tokens | 64,000 actual estimated tokens |
| Recent history retained after compaction | 12,000 tokens | 32,000 tokens |
| Summary allowance / compaction output ceiling | 3,000 tokens | 4,000 tokens |
| Concurrent Z.ai requests per credential | 1 | 1 |

Six calls is a maximum, not a guaranteed allowance: cumulative input may stop Trial 2 before six calls. History counts user text, visible assistant answers, message context and existing summary; excludes hidden reasoning and raw tool results. Count actual content, not maximum generation allowances. A request carries history, the current question, instructions/tool definitions and relevant evidence. Category allowances may borrow unused capacity within the total ceiling.

Before the next provider request, check actual assembled history. Below the threshold include all history that fits. Above it summarize older text and retain recent text unchanged; never compact midway through an answer. Run one non-thinking summary call using the trial's history/input ceiling (instructions included) and summary-output limit. Persist a versioned summary and covered-through message ID. Replace covered text only in model context; originals remain in the database and UI. Later compactions combine the previous summary and newly covered older messages.

The summary prompt preserves explicit user requirements, company/portfolio identities, decisions, comparisons, rejected alternatives and unresolved questions. Preserve dates and evidence references; do not promote earlier financial claims into current facts. Summary calls are separately metered, outside the six answer calls, with tokens and latency recorded alongside the triggering question.

Compaction stays in the same chat. Offer Copy summary and Continue in new chat; never overwrite the clipboard automatically. Keep bounded, ownership-checked `search_conversation_history` for the selected conversation, using PostgreSQL text search and chronological retrieval. Return message IDs, dates, original context and excerpts; cap results at 2,000 estimated tokens within the request budget. No embeddings or cross-chat memory.

If a summary fails, preserve all messages, proceed with bounded recent history and older-message retrieval, visibly show “Older discussion wasn’t summarized,” and suppress automatic attempts until the user chooses Retry summary. Ordinary questions must not repeatedly trigger failed calls.

## Technical architecture

### Frontend workspace

Mount one `AssistantWorkspaceProvider` inside authenticated `AppShell`, above routed content. It owns selected conversation, drafts, messages, drawer state and subscriptions keyed by execution ID. Use one message renderer for drawer and expanded mode. Auto-scroll only near the bottom; otherwise show a new-message indicator. Clear workspace caches on logout/account change.

### Backend interfaces and persistence

Reuse conversations, messages, executions, ownership checks, tool loop and encrypted provider-key handling. Submission accepts validated page context and returns execution and conversation IDs. Store resolved context per user message; current-message scope takes precedence over mutable conversation-level portfolio metadata. Conversation listing adds cursor pagination, latest activity and active-run information. Message history adds pagination, context and terminal outcome; restore saved answer/citation metadata without regeneration.

Add authenticated execution-event subscription/replay and idempotent cancellation endpoints. Migrate message context, execution events, versioned summaries and execution policy/accounting metadata. Encrypt event payloads; sequence monotonically within each execution. Existing maintenance prunes events 24 hours after terminal completion, preserving final messages and summaries.

### Native streaming and recovery

Replace the current complete-answer-only provider stream with actual native streaming. Typed events cover text deltas, completed tool calls, usage and completion. Support direct Z.ai and every existing real provider while preserving tool contracts, tool-name mappings, fragmented argument assembly, Gemini continuation IDs and usage accounting.

Enable chat thinking. Preserve required reasoning blocks server-side through tool continuations in encrypted execution checkpoints. Never render reasoning or add it to visible history. Clear cross-question preserved thinking; visible memory and tool-loop reasoning are separate. Emit concise tool activity without internal reasoning.

Batch durable text chunks at most every 250ms; persist terminal events immediately. Browser uses authenticated fetch streaming, reconnecting from the last sequence and deduplicating replay. Server execution owns generation; browser disconnect never starts or cancels generation. Streamed text is provisional; completion replaces it with the canonical answer after citation resolution and deterministic verification.

Recognize provider truncation (including Z.ai `length`) as incomplete, not successful. Uncertain provider attempts after server restart preserve partial text and show interrupted; no automatic regeneration. Cancellation closes the provider request, releases its slot and persists stopped. Remote provider computation may not stop immediately.

### Budgets and scheduling

Measure the actual serialized provider request including tools and required reasoning/tool continuations. Before every call enforce per-call input, cumulative input/output and call limits. Reserve final-answer capacity before more tool rounds. Reduce unnecessary evidence and duplicate tool material first; never truncate records/arguments into invalid fragments. If essential context cannot fit, return a grounded partial result with an explicit limit state without another model call. Provider usage is authoritative when present; retain conservative estimates otherwise.

Extend existing PostgreSQL Z.ai coordination with interactive/background priority: waiting chat calls precede background calls, FIFO within each class. Running calls finish normally. Bound queue waiting separately from generation deadlines and show Waiting for model truthfully. No automatic paid fallback or repair/retry loop.

Background tuning stays deferred. Preserve deployed profile/event limits. Record later proposed profile 12K input/4K output and digest 16K/6K, thinking enabled, for the later model-optimization backlog.

## Verification and rollout

Implement incrementally: shared workspace/history → provider events/replay → cancellation/recovery → budgets/compaction → replace standalone page. Prepare deployment changes for review after local verification; authorization now permits rollout at that stage.

Required mocked coverage:

- Navigation, closure, expansion, switching and refresh/reconnection preserve the same execution with no duplicated model calls, text or messages.
- OGDC → LUCK and portfolio changes affect only later submissions; saved history preserves citations and original context.
- Stop, timeout, provider error, truncation and uncertain restart have distinct outcomes.
- Fragmented text/tool arguments, reasoning/tool continuation and usage work across supported adapters.
- Compaction preserves covered boundaries, originals and recent messages; retries do not duplicate summaries. Failures warn and suppress automatic retries.
- Ownership covers conversations, history search, summaries, events and cancellation.
- Actual estimated history controls trial thresholds; hidden reasoning never counts as visible history. Both per-call and cumulative limits constrain execution; no automatic Trial 2.
- Keyboard/focus, mobile layout, scrolling, compatibility links, backend/frontend checks and production build pass.

Compare trials on identical approved fixtures: factual/context recall, compaction frequency, budget-exhausted outcomes, provider calls, actual tokens, queue delay, first visible answer and total latency. Activate Trial 2 only explicitly after premature compaction/context loss harms correctness; larger budgets are not presumed better.

## Setup, migration and test commands

Use the repository's existing encrypted provider settings; never put a key in source or frontend state. Run migration on an isolated development database before the updated API. Production migration/deployment is authorized after verification.

```sh
cd apps/api
uv sync
uv run alembic upgrade head
uv run pytest app/tests
cd ../web
npm ci
npm run typecheck
npm test -- --run
npm run build
npm run test:e2e
```

No new seed financial facts are needed: workspace demos use existing seed data and mocked provider fixtures. Ingestion remains deferred. Live-model acceptance is now authorized, but mocked checks do not depend on it.

Server settings: `ASSISTANT_TOKEN_TRIAL=trial1` by default; explicitly set `trial2` and restart the API to select the saved alternative. `ASSISTANT_QUEUE_TIMEOUT_SECONDS=120` bounds each queue wait independently of generation deadlines. Keep the existing single API process: execution tasks and cancellation are owned by that process; credential scheduling uses PostgreSQL across API/research processes.

Disposable PostgreSQL verification (never canonical data): create an empty database whose name starts with `psx_phase11_test_`, set `DATABASE_URL` to that database, then run `PYTHONPATH=. python scripts/verify_phase11_postgres.py` from `apps/api`. It refuses other database names. Drop only that disposable database after verification. Production deployment uses the existing push-to-main workflow: Oracle builds the images, runs `alembic upgrade head`, restarts API/web/research, then checks `/api/ready`.

Verification on 2026-10-03: production frontend build and 24 frontend tests passed. Mocked production-browser acceptance passed navigation, drawer closure/expansion, switching, draft retention, refresh/replay without another submission, canonical citations, mobile layout and Escape. Oracle disposable PostgreSQL verification passed migration upgrade/downgrade/re-upgrade, mock execution, encrypted replay, full-text history search and cross-process chat-before-background priority.

Final focused backend verification passed 65 tests, including fragmented/truncated provider streams, separate queue timeout, duplicate-evidence projection and recovery of a committed response without another model call. TypeScript checks passed.

Live rollout audit: commit `e683e0e` deployed successfully; canonical migration is `0031_assistant_workspace`. Authenticated conversation/history/replay reads passed through the deployed web proxy, and unauthenticated replay returned 401. Chrome accessed the actual Oracle app through the documented SSH tunnel and submitted a real Z.ai chat; that request failed with HTTP 429. A manually inspected identical request returned business code `1305` and the provider's temporary-overload message. A smaller direct request returned HTTP 200 with 178 SSE events. The full request and a variant without tools both returned `1305`; this does not establish continuous global overload or its underlying root cause.

The initial streaming error handler discarded the body after reading it. Corrective handling now uses the same sanitized parser for streaming and ordinary HTTP responses, captures HTTP status/business code/request ID/retry headers, and stores the response body in the existing encrypted attempt payload as `error_response`. Bodies retain all content up to 64 KiB, with original byte count and an explicit truncation flag; credentials are redacted. Raw bodies never enter normal chat or diagnostics exports. In-stream error events are captured too. Failed runs retain a clear provider cause in saved-message metadata; the drawer distinguishes overload (`1305`), request limiting (`1302`) and insufficient resources (`1113`). No automatic retry, regeneration or paid fallback was added. Explicit manual diagnostics are recorded separately from the original response, so later probes cannot rewrite the historical failure.

Further controlled diagnostics: a short system prompt with the same user question received HTTP 200/SSE; the original system prompt without identity received `1305`. A short system prompt with the full tool catalog and an equivalent compact evidence/verification prompt with the full catalog also received `1305`. These are observed HTTP/stream outcomes, not proof of answer quality or the provider's internal overload cause. Production financial instructions and thinking policy were not weakened. The user explicitly authorized sending private portfolio/chat context to Z.ai for these diagnostics. Corrective checks passed 65 backend tests and 26 frontend tests, including encrypted full error-body retention, secret redaction, safe exports and saved failure labels.

Adapter references: [Z.ai thinking continuation](https://docs.z.ai/guides/capabilities/thinking-mode) and [Gemini native streaming events](https://ai.google.dev/gemini-api/docs/streaming). Trial comparison with live models remains a measurement exercise before explicitly activating Trial 2; mocked fixtures validate policies and preservation, not real-model financial quality.

The broader backend run passed 423 tests and reproduced three existing failures on the unchanged HEAD: `test_company_research_exposes_normalized_event_publishers`, `test_company_and_portfolio_apis_surface_only_direct_subjects_with_exact_weight`, and `test_scheduler_reconstructs_live_before_historical_from_postgres`. The first two use raw events without the indexed evidence now required by the existing read path; the last uses a fixed historical date outside current retention. These are deferred fixture/data-path issues, not silently skipped checks or Phase 11 changes.

## Ordered follow-up — outside Phase 11

1. **Oracle deployment and ingestion audit, then activation.** Verify deployed services, free-tier constraints, actual disk allocation/free space, database/index/report/container growth, backup/retention needs, worker throughput, queue delay, failures and successful source/company coverage. Identify stale/missing data. Then backfill recent data and enable continuous relevant market/news ingestion with verified headroom and bounded concurrency.
2. **Company coverage and agent usefulness.** Fix missing basics, PSX-heavy coverage, weak timely news and unfinished earlier issues. Automatically assemble investor context and relevant evidence in one conversation. Improve measured latency, token use and costs instead of requiring manual evidence requests.
3. **UI overhaul.** Consider Figma, remove debugging/clutter, renew login, add charts and deterministic company ratios such as debt/equity from validated facts and periods.
4. **Phase 6.5 model.** Revisit the existing deterministic event-impact specification after its data dependencies improve.
5. **Aggressive cleanup.** Remove unused code, speculative scaffolding and redundant abstractions. Make deletion/consolidation explicit goals and verify surviving workflows.

Do not pull these steps into Phase 11.
