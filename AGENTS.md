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
