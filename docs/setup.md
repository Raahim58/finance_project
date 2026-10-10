# Setup

## Backend

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../../.env.example .env
python -m app.core.keys
```

Put the generated Fernet key in `ENCRYPTION_KEY`. User LLM keys are encrypted at rest, never returned after save, and decrypted server-side only for an LLM request.

The Phase 8 Assistant uses one model-directed, read-only native tool loop. New Gemini
Assistant runs use the stateful Interactions API: the first turn sends the question,
while later turns send `previous_interaction_id` and only new function results. Gemini 3
models do not receive Google Search or URL Context: model support does not guarantee the
configured Google project has web-tool quota. External verification is reported missing.
Assistant requests are owned by the API process and persisted in PostgreSQL; no Assistant Celery
worker is used. Apply migrations through `0029_assistant_tool_loop` before starting the
API. The migration adds the encrypted transcript checkpoint used for restart recovery.

`ASSISTANT_EXECUTION_DEADLINE_SECONDS` defaults to one 300-second outer deadline for
every Assistant request. `ASSISTANT_EXECUTION_INPUT_TOKEN_LIMIT` defaults to 200,000
cumulative estimated input tokens. Before every provider turn the estimate includes the
entire retained logical context, native tool schemas, and images; this remains the
safeguard even though Gemini continuations transmit only new results. Diagnostics track
transmitted bytes and provider-reported input/output/cache/reasoning separately, then
reconcile the conservative reservation to reported input. `ASSISTANT_MAX_TOOL_ITERATIONS`
retains the operator-configured call safeguard. Cost-unit scoring and its configuration
have been removed; see `docs/mcp-tools.md` for concrete tool workload bounds.
The older `PHASE8_*_DEADLINE_SECONDS` settings remain for non-Assistant compatibility
consumers and do not select budgets in the new Assistant path.

Start production-style dependencies and migrate:

```bash
cd ../..
docker compose up -d
cd apps/api
alembic upgrade head
```

SQLite can be used without Docker:

```bash
DATABASE_URL=sqlite+pysqlite:///./psx_ai_local.db alembic upgrade head
```

The API reconciles queued and abandoned Assistant runs at startup and every 20 seconds.
It runs at most two local executions concurrently. A sent external-provider attempt
without a recorded outcome is marked uncertain and fails explicitly to avoid a duplicate
paid request. The local mock provider retains its single retry allowance. Retry and input
counters remain in the execution row across restarts. Persisted provider turns,
associated tool results, and Gemini interaction IDs resume from the encrypted transcript;
provider/model selection cannot change mid-execution. An expired Gemini interaction
fails explicitly rather than replaying the chain.

Execution status and supporting evidence are available in the Assistant workspace.
Captured provider payloads remain internal and encrypted; retired diagnostic/replay
CLI commands are no longer part of the supported operator interface.

Metadata and attempt accounting are retained for one year. Encrypted captured payloads
are retained for failed executions and a deterministic 10% success sample for 14 days,
subject to `PHASE8_DIAGNOSTIC_PAYLOAD_BYTES` (default 1 GiB). Exports exclude prompts,
response bodies, holdings, allocation amounts, documents, and credentials.

Run the focused conformance suites without provider credentials:

```bash
pytest app/tests/test_context_builder.py app/tests/test_context_deficiencies.py app/tests/test_context_ingestion.py \
  app/tests/test_context_consumers.py \
  app/tests/test_assistant_execution.py app/tests/test_allocation_calculation.py app/tests/test_evidence_projection.py app/tests/test_tool_loop_*.py \
  app/tests/test_tool_registry.py app/tests/test_quant_domain.py \
  app/tests/test_intelligence_v1.py app/tests/test_providers.py \
  app/tests/test_llm_provider_usage.py -q
```

Run the Phase 8 Phase 1 read-tool fidelity suite separately while iterating on evidence
contracts (it performs no network, ingestion, broker, or model calls):

```bash
pytest app/tests/test_read_tool_contracts.py app/tests/test_company_read_tools.py app/tests/test_document_read_tools.py app/tests/test_allocation_verification_tools.py -q
```

Run the Phase 2 native-provider and durable-loop acceptance suite without network or
paid model calls:

```bash
pytest app/tests/test_tool_loop_*.py \
  app/tests/test_llm_provider_usage.py app/tests/test_tool_registry.py -q
```

Seed the demo investor state (demo user, ledger-backed holdings and cash,
historical cost basis, investor profile, confirmed IPS, target allocation, and
monitoring preferences). This default path creates no market prices, macro
observations, company reports, financial facts, or events:

```bash
DEMO_USER_PASSWORD='choose-a-local-password' python -m app.seed.demo
```

The demo login is `portfolio.manager@example.com`. The command is idempotent and
never seeds an LLM key. Run live ingestion after this command to create the
hybrid environment: synthetic investor state plus observed external-world data.

For isolated offline development only, the old deterministic external-world
fixtures remain explicitly available:

```bash
DEMO_USER_PASSWORD='choose-a-local-password' python -m app.seed.demo --with-mock-world
```

Never use `--with-mock-world` in an `auto`, `dps`, or other live-data database.
Even if old mock rows exist, live modes exclude them from canonical prices,
market screens, portfolio valuation, and quant inputs.

Run the API and the pipeline scheduler/workers (see [Pipeline restoration](PIPELINE_RESTORATION.md)
for the stage-to-queue map; `compose.oracle.yml` is the reference deployment):

```bash
uvicorn app.main:app --reload
python -m app.jobs.pipeline_scheduler
celery -A app.celery_app worker -n pipeline-parse@%h -Q pipeline_parse --concurrency=1 --loglevel=INFO
```

Canonical macro ingestion has its own Postgres-led queue producer:

```bash
celery -A app.celery_app worker -P threads -n macro@%h -Q macro --concurrency=4 --loglevel=INFO
MACRO_INGESTION_ENABLED=true python -u -m app.jobs.macro_scheduler
python -m app.jobs.macro_status
```

Use `python -m app.jobs.macro_status` to inspect configured series, provider
ladders and coverage; `macro_backfill` remains the explicit bounded recovery tool.

The live universe is synchronized from observed DPS symbol data; there is no configured stock list. History and report work is recorded in the Postgres stage-run outbox (`ingestion_stage_runs`) and dispatched by `pipeline-scheduler`, so it survives a Redis loss. The market scheduler remains separate.

`MARKET_DATA_MODE=mock` is development-only. `dps` uses the verified direct DPS adapter. A failed live refresh retains prior observed rows and records failure/staleness; it never generates mock replacements. NCCPL remains a manual CSV import because ordinary retrieval is blocked; no anti-bot bypass is implemented.

DPS latest-price coverage uses the currently observed DPS ordinary-equity universe
as its denominator. A response that omits any ordinary symbol is recorded as
`partial` with the missing symbols and accepted/rejected counts; SCSTrade
rows never satisfy DPS health. DPS standardized company-page facts are exposed as
observed secondary fundamentals, while facts extracted from official filings retain
precedence for the same metric and period.


Mettis is scheduled only through this evidence pipeline. It is intentionally not
also run by the generic market/macro scheduler, which prevents duplicate ingestion
paths with different entity-linking and story-deduplication behavior.

Historical official-source canary jobs remain disabled by default. Current pipeline
operation and source controls are documented in [Pipeline restoration](PIPELINE_RESTORATION.md).

Workers and schedulers are opt-in Compose profiles: `docker compose up -d` starts
only PostgreSQL and Redis. Use `--profile ingestion` for explicitly selected
workers and `--profile scheduling` for explicitly selected producers; neither
profile's services restart automatically. Phase 2 workers do not consume evidence queues. Live messages use Redis priority `0`;
historical hydration uses priority `8`, concurrency two, and a separate queue. Every
worker mounts the same `SOURCE_ARTIFACT_ROOT` because temporary bodies move between
stages through `.evidence-spool`; Redis messages contain IDs only. Postgres leases and
candidate state reconstruct lost work after broker or worker failure.

## Frontend

```bash
cd apps/web
npm install
npm run generate:api
npm run typecheck
npm test
npm run build
npm run dev
```

`generate:api` expects the API at `http://localhost:8000` and checks `lib/generated/api.d.ts` into the repository. Main portfolio routes are `overview`, `build`, `quant`, `risk`, `scenarios`, `research`, `activity`, and `ips`.

Browser requests default to the same-origin `/api` path. Next.js proxies that path to
`API_INTERNAL_BASE_URL` (default `http://127.0.0.1:8000`), so an HTTPS development
tunnel only needs to expose the frontend:

```bash
cd apps/api
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

cd ../web
npm run dev -- --hostname 0.0.0.0

cloudflared tunnel --url http://localhost:3000
```

Do not set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` for a remote preview: the
remote browser would try its own localhost and HTTPS pages may block the HTTP request.

## Verification

```bash
cd apps/api
.venv/bin/python -m pytest -q
DATABASE_URL=sqlite:////tmp/psx-migration.sqlite alembic upgrade head

cd ../web
npm run typecheck
npm test
npm run build
```

Provider parser tests use bounded fixtures and never hit live services. Live contract smoke tests are opt-in and should remain low-rate. See [migration baseline and transition](../apps/api/alembic/README.md) for populated-legacy and downgrade checks.

The API-level pytest bootstrap forces an in-memory SQLite database, test bcrypt cost, disabled demo access, mock market mode, and disabled scheduled ingestion before the application package is imported. A developer `.env` therefore cannot silently redirect the test suite to local Postgres or enable source traffic. Global Evidence Pass 0 contains contracts and schema only; it has no live smoke test or provider setup command.

## Documents and RAG

Manual uploads are available in Research (`/research`) under **Upload document**.
The supported market route is `/market`; `/markets`, `/documents`, `/portfolio`,
and the portfolio `stress` and `settings` aliases have been removed. Use
`/portfolios/{id}/scenarios` and `/portfolios/{id}/ips` respectively.
This UI cleanup requires no migration or new seed data.

For production semantic retrieval, set `EMBEDDING_BACKEND=sentence_transformers` and install requirements. PostgreSQL stores 384-dimensional vectors with an indexed cosine search; SQLite stores vectors as JSON and scans only for tests/local use. Private uploads must be queried through their owner/portfolio scope.

## Event intelligence

Classification and event normalization run as pipeline stages (`classify`, `events`); see
[Pipeline restoration](PIPELINE_RESTORATION.md) for event classification, deterministic
boundaries, and read APIs.

## Safety assumptions

No broker password storage, browser automation, or trade placement exists. Rebalance output is only a proposal. Market prices and exact portfolio values come from database queries, while document retrieval supplies narrative evidence only.

## Focused Assistant correction

No migration or new seed is required. The existing encrypted execution/checkpoint and
`AnalysisRun` fields support normalized evidence, local finalization recovery and versioned
saved-analysis reuse. Assistant reads calculate in memory on a cache miss and do not save
analytics. The only added model tool is the database-backed, section-selectable
`market.overview`; universe screening remains optional on the existing tool.

Run the isolated backend boundary once, then the browser checks:

```bash
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash \
  apps/api/.venv/bin/python -m pytest apps/api/app/tests -q
cd apps/web
npm test
npm run typecheck
npm run build
```

No live provider call, external search or streaming is required for these offline checks.


## Local tokenizer assets

Install the data-only tokenizer assets after installing the backend dependencies:

```bash
cd apps/api
.venv/bin/python scripts/setup_glm_tokenizer.py
```

Docker installs these assets during the API image build. Missing assets use the
explicit conservative counting fallback; no request-time model download is required.

## Assistant finalization recovery

For a failed serialization/rendering/persistence execution, run this server-side recovery
from `apps/api` with the application's normal server configuration. Use the owning user ID
and exact failed execution ID; the helper refuses uncertain attempts and non-final turns:

```bash
python - <<'PY'
from app.db.session import SessionLocal
from app.services.assistant_execution import queue_finalization_recovery
with SessionLocal() as db:
    queue_finalization_recovery(db, 'OWNING_USER_ID', 'FAILED_EXECUTION_ID')
PY
```

The existing API maintenance loop schedules the queued execution. Expired provider-work
deadlines do not block purely local finalization. No external attempt is scheduled during
this recovery. Diagnostics expose safe failure locations in the execution's stage metadata.
