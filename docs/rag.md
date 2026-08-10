# Document Retrieval

Documents carry owner, visibility (`public` or `private`), optional portfolio, artifact, extraction version, and parser version. Retrieval combines structured filtering and semantic/lexical ranking, and returns citation metadata containing the real document title, URL, page, and bounded snippet.

PostgreSQL uses a configured 384-dimensional pgvector column and cosine index. `EMBEDDING_BACKEND=sentence_transformers` uses normalized semantic embeddings from the configured model (default `sentence-transformers/all-MiniLM-L6-v2`). `hash` remains a labeled development/test fallback and retains lexical gating. Changing the backend requires `python -m app.jobs.reindex_rag`; incompatible chunk embeddings are skipped. Chunks preserve original casing, punctuation, line breaks, page number, and detected section headings.

RAG is exclusively for unstructured document text. Prices, financial facts, macro observations, holdings, portfolio values, P&L, and quant metrics come from structured database queries. Search never fabricates source metadata, and a private document is visible only to its owner and, where linked, its portfolio scope.
