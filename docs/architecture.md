# Architecture

`psx-ai-portfolio-agent` is a monorepo with a Next.js frontend and FastAPI backend.

## Current Phases

Phase 0 creates the repository shape, local services, docs, and skeleton apps.

Phase 1 implements:

- Email/password authentication
- Backend-issued JWT access tokens
- User preferences
- Encrypted bring-your-own LLM API key storage
- Provider-agnostic LLM interface
- Mock provider for tests

## System Shape

```text
apps/web  ->  apps/api  ->  database
                 |
                 -> LLM provider registry
                 -> encrypted user provider keys
```

Structured numerical data will live in database tables in later phases. RAG will be used only for unstructured company, policy, and report documents.

## Phase Boundaries

Market data, portfolio analytics, RAG, policy intelligence, daily digest, alerts, and order intents are intentionally deferred until the repo runs locally and Phase 1 tests pass.
