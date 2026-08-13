# PSX Quant Portfolio Workstation

A FastAPI + Next.js workstation for user-owned PSX portfolios, ledger-based valuation, reproducible quant analysis, optimization, research/RAG, deterministic scenarios, and a grounded assistant.

Implemented capabilities include:

- Authentication, encrypted bring-your-own LLM keys, and strict user ownership.
- Generic instruments, aliases, source artifacts, ingestion runs, canonical observations, and quality issues.
- Multiple portfolio lifecycle, settlement-aware cash/transaction ledger, cash-flow-adjusted performance, daily snapshots, recorded split/dividend application, target/sandbox/optimized allocations, and typed/versioned IPS inputs.
- Canonical selected observations, source-priority reconciliation, quality issues, historical backfill/gap reporting, explicit PSX calendar overrides, and compatibility caches.
- Realized CAGR and arithmetic expected return, target downside risk, excess-return Jensen alpha, CAPM inputs, risk contributions, event studies, cash-aware optimization, path scenarios, and post-rounding rebalance validation.
- Structured macro/fundamental/event data kept separate from private/public document retrieval and pgvector search.
- One bounded multi-turn assistant with real OpenAI/Anthropic/Gemini/OpenRouter transports, an allowlisted typed tool planner, claim/evidence validation, recommendations, monitoring runs, and deduplicated alerts.
- Portfolio, market, research, stress, and assistant workspaces in the frontend, with generated OpenAPI contracts and ECharts.

The application never automates broker passwords or places trades. Mock market data is development-only; all exact values are queried from stored structured data and advice-like assistant output carries evidence or states what is missing.

## Quick start

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../../.env.example .env
python -m app.core.keys
alembic upgrade head
DEMO_USER_PASSWORD='choose-a-local-password' python -m app.seed.demo
python -m app.jobs.scheduler --once
uvicorn app.main:app --reload
```

The seed creates hypothetical investor-owned state only. The scheduler fills the
external-world plane from configured real providers. Use
`python -m app.seed.demo --with-mock-world` only for isolated offline fixture
development with `MARKET_DATA_MODE=mock`.

```bash
cd apps/web
npm install
npm run generate:api
npm run dev
```

See [setup](docs/setup.md), [architecture](docs/architecture.md), [data sources](docs/data-sources.md), [formulas](docs/formulas.md), [assistant tools](docs/mcp-tools.md), and [trading safety](docs/trading-safety.md).
