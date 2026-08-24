# AGENTS.md

Project rules for `psx-ai-portfolio-agent`.

- Always work incrementally.
- Prefer small, testable modules.
- Never hardcode secrets.
- Never invent financial facts.
- Every advice-like answer must cite evidence or state data is missing.
- Never implement password-based broker automation.
- Never place trades without explicit confirmation.
- Separate structured numerical data from RAG document retrieval.
- Use database queries for exact values.
- Use vector search only for document text.
- Add tests for critical modules.
- Keep UI simple but clean.
- Include setup commands.
- Include migration commands.
- Include seed/demo data when the relevant phase is implemented.
- Explain assumptions in docs.
- User LLM API keys must never be returned to the frontend after save.
- Store user LLM API keys encrypted at rest.
- Decrypt LLM keys only server-side immediately before an LLM call.
- Never log full API keys.
- Phase 2 market data is mock/demo data unless a source field states otherwise.
- Market prices, rankings, snapshots, and sector stats must come from database queries.
- Phase 3 portfolio values and PnL must be calculated from stored holdings and database market prices.
- Enforce user ownership checks on every portfolio, holding, and transaction operation.
- Phase 4 RAG is for unstructured document text only; exact numerical values still come from database queries.
- RAG search results must return citation metadata and must not fabricate source titles, URLs, snippets, or page numbers.
- Market data architecture must assume automatic current-data ingestion; mock mode is development-only.
- Agent decisions must consider market freshness and portfolio source metadata before presenting analysis.

## Agent skills

### Issue tracker

Issues and specifications are tracked in GitHub Issues for `Raahim58/finance_project`. See `docs/agents/issue-tracker.md`.

### Domain docs

This repository uses a single-context domain documentation layout. See `docs/agents/domain.md`.
