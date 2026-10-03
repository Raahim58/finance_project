# Input counting implementation (uncommitted)

This changes counting, not the locked Trial 1/Trial 2 ceilings, output limits, call allowance or provider selection. No live generation requests or deployment were performed for this patch.

## Anthropic

The conservative local estimate remains the cheap first pass. When it reaches 80% of the smaller of the per-call input ceiling and remaining cumulative input allowance (including an apparently oversized request), request `/v1/messages/count_tokens` using the same model, messages, system instructions, tools, tool choice and thinking settings. Exclude HTTP/generation controls such as stream and max_tokens. Use the returned input count for the reservation and ceiling checks. Counting does not consume a generation-call allowance. Each preflight has a five-second maximum, no retry and no fallback generation. If counting fails, retain the conservative estimate and record the error type; never bypass a limit. The provider endpoint returns an estimate, not a guarantee of identical eventual usage.

Provider documentation: https://platform.claude.com/docs/en/build-with-claude/token-counting

## Direct GLM-4.5

Use official Z.ai GLM-4.5-Air tokenizer data and chat template from immutable revision `a24ceef6ce4f3536971efe9b778bdaa1bab18daa`; verify both SHA-256 values before loading. Render actual messages and tools, including required reasoning/tool continuation, then tokenize locally with a 5% safety margin. Exclude generation/transport settings. Parse function argument JSON for rendering without changing the transmitted payload. No remote Python code, model weights, inference call or automatic request-time download is involved.

This is a local estimate of the hosted Flash prompt, not an exact public hosted tokenizer contract. Restricted to the GLM-4.5 family; do not assume GLM-4.7 compatibility. Unknown models, missing assets and multimodal GLM payloads use an explicitly labelled conservative fallback. Invalid checksums fail instead of loading altered data.

Assets: https://huggingface.co/zai-org/GLM-4.5-Air/tree/a24ceef6ce4f3536971efe9b778bdaa1bab18daa

Offline replay of the two captured GLM-4.5-Flash calls:

| Request | Provider-reported input | Published-template count | With 5% margin | Warm median on local workstation |
|---|---:|---:|---:|---:|
| Initial price lookup | 4,283 | 4,508 | 4,734 | 6.94 ms |
| Tool continuation | 25,566 | 25,791 | 27,081 | 32.71 ms |

Unmargined errors were +5.25% and +0.88%; the constant 225-token excess is consistent with a template difference, but is not subtracted based on only two examples. Two requests do not validate every language/tool/history shape. Local cold initialization was 609 ms and is warmed during API startup; Oracle latency has not been measured. The old estimates were 10,374 and 46,257. Captured private prompts remain outside Git.

Visible history and missing-usage output estimates use local vocabulary counting with the same 5% margin, with the previous conservative estimator available when assets are absent. This is estimated history accounting, not a claim that GLM and Anthropic share a tokenizer. Summaries use the same assembled-request preflight, and record counting metadata separately from answer generation. Provider-reported generation input/output remains authoritative and reconciles reservations after completion.

## Setup and verification

Install the existing API dependencies including explicitly pinned tokenizers/Jinja dependencies, then install the data-only assets (approximately 20 MB):

```sh
cd apps/api
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/setup_glm_tokenizer.py
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash .venv/bin/python -m pytest app/tests/test_token_counting.py app/tests/test_phase11_workspace.py app/tests/test_phase8_phase2_tool_loop.py app/tests/test_llm_provider_usage.py app/tests/test_zai_provider.py app/tests/test_phase8_revamp.py app/tests/test_tool_registry.py app/tests/test_canonical_market.py app/tests/test_phase8_phase1_read_tools.py -q
```

No migration or seed changes. Docker installs the pinned assets during build; the ignored local copies are excluded from its build context. Tests mock the separate count endpoint so fixture/private context cannot be sent by the test suite. Regression coverage includes 49,217 local versus 32,640 provider-counted input acceptance, actual-usage reconciliation, unchanged call accounting, true per-call/cumulative threshold selection, count failure, tool/reasoning preservation and transport exclusion.
