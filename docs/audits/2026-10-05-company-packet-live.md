# Compact evidence live verification — 2026-10-05

Isolated containers used the existing Oracle database, stored provider keys and real authenticated `/assistant/messages` endpoint. These were backend integration tests, not browser UI tests. No preferences, holdings or trades were changed. Production containers were not replaced. New source remains uncommitted.

## Warm retrieval runs

Tokens below are provider-reported totals across the question, not per-call counts. Existing token/tool limits remained unchanged. Warmup was measured separately from request latency.

| Provider / question | Seconds | Model calls | Backend reads | Input / output tokens | Resolved sources | Result |
|---|---:|---:|---:|---:|---:|---|
| Anthropic claude-sonnet-5 / LUCK | 45.99 | 1 | 6 | 25,190 / 4,501 | 35 | Completed, cited answer; financial reporting bases identified |
| Anthropic claude-sonnet-5 / portfolio | 115.99 | 3 | 7 | 88,405 / 9,976 | 10 | Completed; allocation.verify succeeded, accepted candidate, evidence still limited |
| Z.ai glm-4.5-flash / LUCK | 87.02 | 1 | 6 | 18,985 / 1,165 | 0 | Quality failure: omitted citations, mixed reporting bases and interpreted footnote 37 as EPS instead of structured 52.53 |
| Z.ai glm-4.5-flash / portfolio | 89.23 | 2 | 5 | 32,343 / 1,991 | 3 | Quality failure: suggested cash weights without verification despite seven backend calls remaining |

No 429 occurred in these tests. HTTP completion alone is not a quality pass. These are small-sample measurements, not latency guarantees or proof that all interpretation is correct. No new repair calls or allocation workflow were added to hide failures.

Earlier cold runs timed out the news search at the existing 10-second tool deadline. Local embedding initialization took 15.77–16.92 seconds; warmed searches took about 1.2–1.6 seconds. The user authorized preloading the existing model at API startup, keeping all deadlines unchanged.

## Startup verification

A fresh isolated API lifespan loaded the real embedder before serving: startup 16.73 seconds, `/ready` HTTP 200, first `research.search` successful in 545.948 ms with five sources under its unchanged deadline. The smoke harness suppressed execution maintenance only within its isolated test process so it would not schedule unrelated saved executions. No external LLM request was made by this smoke test.

Offline verification: 135 targeted tests and 69 regression tests passed. Startup preload failures log only the exception class; unrelated API startup continues and retrieval reports its normal availability outcome.

Complete response/usage records are in ignored `data/audits/company-packet-live-results.json`, not committed documentation. One GLM company run's execution ID is omitted: the harness's latest-row lookup overlapped the concurrent Anthropic run; response metrics and answer came directly from its own HTTP response.
