# Document Retrieval

Documents carry owner, visibility (`public` or `private`), optional portfolio, artifact, extraction version, and parser version. Retrieval combines structured filtering and semantic/lexical ranking, and returns citation metadata containing the real document title, URL, page, and bounded snippet.

PostgreSQL uses a configured 384-dimensional pgvector column and cosine index. SQLite keeps a deterministic JSON-vector fallback for tests. Embeddings are reproducible placeholders and can be replaced by a versioned provider without changing citation or visibility rules.

RAG is exclusively for unstructured document text. Prices, financial facts, macro observations, holdings, portfolio values, P&L, and quant metrics come from structured database queries. Search never fabricates source metadata, and a private document is visible only to its owner and, where linked, its portfolio scope.
