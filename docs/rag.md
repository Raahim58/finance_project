# RAG Design

Phase 4 implements the first local RAG pipeline.

- Use deterministic chunking.
- Preserve document metadata: symbol, sector, document type, fiscal year, quarter, URL, page number.
- Return citation objects separately from answer text.
- Use structured filters before vector search.
- Use keyword fallback when vector search is unavailable.
- State missing data instead of inventing claims.

Exact prices, holdings, and calculated financial values must come from database queries, not vector retrieval.

## Current Implementation

- Tables: `documents`, `document_pages`, `document_chunks`, `citations`
- Text/Markdown upload and local-file ingestion are supported.
- PDF parsing is attempted only when optional dependency `pypdf` is installed.
- Chunks use deterministic token windows with overlap.
- Embeddings are local hash vectors stored as JSON so SQLite tests and PostgreSQL runs behave consistently.
- Retrieval applies structured filters first and returns only chunks with lexical overlap to avoid unrelated false-positive citations.

pgvector, external embedding APIs, rerankers, and AI-assisted table extraction are deferred.
