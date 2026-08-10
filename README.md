# PSX Quant Portfolio Workstation

A FastAPI + Next.js workstation for user-owned PSX portfolios, ledger-based valuation, reproducible quant analysis, optimization, research/RAG, deterministic scenarios, and a grounded assistant.

Implemented capabilities include:

- Authentication, encrypted bring-your-own LLM keys, and strict user ownership.
- Generic instruments, aliases, source artifacts, ingestion runs, canonical observations, and quality issues.
- Multiple portfolio lifecycle, cash/transaction ledger, derived holdings, baseline snapshots, target/sandbox/optimized allocations, profile and IPS versioning.
- Returns, risk, performance, covariance, regression, optimizer methods, risk contributions, scenarios, and rebalance previews.
- Structured macro/fundamental/event data kept separate from private/public document retrieval and pgvector search.
- One bounded assistant using an allowlisted typed tool registry, plus recommendations, monitoring runs, and deduplicated alerts.
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
python -m app.seed.demo
uvicorn app.main:app --reload
```

```bash
cd apps/web
npm install
npm run generate:api
npm run dev
```

See [setup](docs/setup.md), [architecture](docs/architecture.md), [data sources](docs/data-sources.md), [formulas](docs/formulas.md), [assistant tools](docs/mcp-tools.md), and [trading safety](docs/trading-safety.md).
