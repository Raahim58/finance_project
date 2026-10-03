# Direct Z.ai provider

Provider ID: `zai`. Default model: `glm-4.7-flash`.
Endpoint: `https://api.z.ai/api/paas/v4/chat/completions` (standard API, not Coding Plan).

In Settings → AI providers, choose zai, enter the key and save. The existing key service encrypts it at rest and selects zai as the user's preferred provider. Full saved keys are never returned. Saving accepts key format without triggering inference; authentication/model availability is not verified until an explicitly authorized call.

Requests use native function tools, existing output/deadline limits, and thinking disabled. No native paid web-search tool is enabled. In-flight requests sharing a credential are serialized with a process-local lock and a PostgreSQL advisory lock across API/worker containers. Different external applications using the same account are outside this lock. Z.ai account-level limits can still return 429. No automatic retry or paid fallback is introduced.

Parallel local database tools do not create parallel provider requests. The official API does not document `parallel_tool_calls`, so that parameter is not sent.

Verified account concurrency for GLM-4.7-Flash: 1. No daily token/request quota was shown. This is not an unlimited-use guarantee. The dashboard's >8K throttling note explicitly names GLM-4-Flash, not GLM-4.7-Flash.

Setup/deployment:

```sh
docker compose -f compose.oracle.yml build api web
docker compose -f compose.oracle.yml up -d --no-deps api web
apps/api/.venv/bin/python -m pytest apps/api/app/tests/test_zai_provider.py apps/api/app/tests/test_providers.py apps/api/app/tests/test_llm_provider_usage.py apps/api/app/tests/test_llm_keys.py -q
```

Migration: none. Do not start ingestion/research workers as part of provider setup.

Official references:
- https://docs.z.ai/guides/overview/pricing
- https://docs.z.ai/api-reference/llm/chat-completion
- https://docs.z.ai/api-reference/api-code
- https://z.ai/manage-apikey/rate-limits
- https://docs.z.ai/devpack/usage-policy (Coding Plan; does not substantiate claims about standard API automation bans)
