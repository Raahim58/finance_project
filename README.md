# psx-ai-portfolio-agent

AI-powered Pakistan Stock Exchange portfolio intelligence assistant.

This repository is a production-style side-project MVP scaffold. Phase 0 and Phase 1 are implemented first:

- Monorepo layout with `apps/api` and `apps/web`
- FastAPI backend skeleton
- Next.js App Router frontend skeleton
- Email/password authentication
- User preferences
- Bring-your-own LLM provider settings
- Encrypted LLM API key storage
- Provider-agnostic LLM gateway with mock provider and adapter placeholders
- Project docs, skills, agents, and MCP-style design notes

Later phases for market data, portfolio analytics, RAG, policy intelligence, digests, and order intents are intentionally not implemented yet.

## Quick Start

Backend:

```bash
cd apps/api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../../.env.example .env
python -m app.core.keys
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
