# RAG Design

RAG is deferred beyond Phase 1.

When implemented:

- Use deterministic chunking.
- Preserve document metadata: symbol, sector, document type, fiscal year, quarter, URL, page number.
- Return citation objects separately from answer text.
- Use structured filters before vector search.
- Use keyword fallback when vector search is unavailable.
- State missing data instead of inventing claims.

Exact prices, holdings, and calculated financial values must come from database queries, not vector retrieval.
