# Global Evidence Pass 1

Pass 1 is the first complete, synchronous evidence slice. It is deliberately
small enough to fixture-test without Redis, Celery, browsers, paid APIs, or an LLM.

```text
configured discovery
  -> lightweight candidate + cursor in Postgres
  -> metadata-only relevance gate
  -> selective fetch and temporary extraction
  -> canonical URL / SHA-256 / SimHash deduplication
  -> bounded topic-time-entity story clustering
  -> one primary, one reporting, and optional context slot
  -> selected artifact + Document/Page/Chunk/Citation only
```

## Direct and generic coverage

- PSX announcements use the observed company-announcement POST fields and table
  response. The normalized record includes symbol, company, ID, category,
  timestamp, attachment location and type. High-value attachment categories are
  fetched once through content-addressed artifact storage; routine categories stay
  metadata-only.
- Dawn and Business Recorder use the generic RSS/Atom adapter.
- Mettis reuses its verified listing parser and the generic article extractor.
- SBP and IMF releases use bounded official listing-page discovery.
- GDELT DOC 2 provides bounded global discovery using configured queries.
- The reusable sitemap adapter supports standard and Google News XML sitemaps.

Article extraction checks `NewsArticle`/`Article` JSON-LD first, including `@graph`,
then extracts substantive paragraphs from `article` or `main`. It calculates local
hashes and important-number fingerprints. Those number strings are evidence
metadata only: no `MacroObservation`, market price, financial fact, holding, or PnL
row is created from narrative text.

## Storage behavior

Discovery candidates never store full bodies. Rejected and duplicate candidates
keep URLs, metadata, scores, reasons, and fingerprints. Selected raw content is
gzip-compressed in the existing artifact store; selected clean text is passed to
the existing RAG document pipeline. Exact market and portfolio answers continue to
come from structured database queries.

## Intentional Pass 2 boundary

Pass 1 has a manual bounded runner only. Pass 2 owns evidence-only Celery queues,
live-first scheduling, retries/backoff, circuit breakers, DNS-level/advanced response hardening,
candidate retention/expiry, historical hydration, queue reconstruction,
operational statistics APIs, and the bounded on-demand refresh endpoint. No Phase
4–6 reasoning or entity-intelligence feature is implemented here.

## Verification

```bash
cd apps/api
alembic upgrade head
pytest -q
ruff check app
```
