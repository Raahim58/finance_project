# psx-ai-portfolio-agent

AI-powered Pakistan Stock Exchange portfolio intelligence assistant.

This repository is a production-style side-project MVP scaffold. Phases 0 through 4 are implemented:

- Monorepo layout with `apps/api` and `apps/web`
- FastAPI backend skeleton
- Next.js App Router frontend skeleton
- Email/password authentication
- User preferences
- Bring-your-own LLM provider settings
- Encrypted LLM API key storage
- Provider-agnostic LLM gateway with mock provider and adapter placeholders
- Project docs, skills, agents, and MCP-style design notes
- Mock PSX market data tables, ingestion job, APIs, dashboard, and company history pages
- Portfolio tables, holdings and transactions APIs, valuation/exposure/PnL services, risk flags, and portfolio dashboard
- Company document ingestion, deterministic chunking, local RAG retrieval, citations, and document search UI

Later phases for policy intelligence, chat, digests, alerts, watchlists, and order intents are intentionally not implemented yet.

## Quick Start

Backend:

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../../.env.example .env
python -m app.core.keys
alembic upgrade head
python -m app.jobs.ingest_psx_mock --days 365
python -m app.jobs.ingest_document --file ./sample.txt --symbol MEBL --type annual_report
pytest
uvicorn app.main:app --reload
```

Frontend:

```bash
cd apps/web
npm install
npm run dev
```

Full setup details are in [docs/setup.md](docs/setup.md).
