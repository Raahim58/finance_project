# Curated sector news and retrieval — Oracle, 2026-10-04

## Scope and actual ingestion

This implements a small material-news batch and retrieval changes. It does not change model budgets, allocation logic, benchmarks, splits, numerical market feeds or continuous scheduler activation. No external LLM calls were made for this work. Numerical facts remain database-tool inputs; news retrieval supplies unstructured evidence.

The bounded Oracle job inspected 487 feed/archive entries, fetched 29 articles and initially indexed 19. Title review caught five AI tooling/security/tutorial articles; these are retained but marked `excluded_irrelevant`, and their event sources are excluded. Fourteen articles remain usable. Originals, citations and embeddings are preserved.

| Publisher | Discovery entries | Initial shortlist | Usable indexed articles |
|---|---:|---:|---:|
| World Fertilizer | 20 | 3 | 3 |
| World Cement | 20 | 2 | 2 |
| OilPrice | 15 | 3 | 3 |
| Cotton Grower | 12 | 2 | 1 |
| MetalMiner | 11 | 8 | 0 |
| Semiconductor Engineering | 64 | 5 | 0 |
| FreightWaves | 123 | 8 | 1 |
| Guardian World | 112 | 5 | 4 |
| Medium / Kahloon Journal | 10 | 0 | 0 |

Medium was inspected, but none of this publication's feed entries qualified for the recent-date/material-news selection. It is commentary, not an authoritative numerical source. No paywall workaround or undated article ingestion is enabled.

Selection uses actual article dates, title/body topic and sector matches, minimum body length, preview exclusions and source budgets. Discovery ranks relevant candidates before full fetching; full parsing checks relevance again. It does not assert an effect on any company. The AI interprets the evidence when it chooses retrieval.

History is deliberately sampled: current feeds plus one seven-day window around 30/60 days ago for verified WordPress archives, and Guardian listings from three sampled dates. This is **not complete 90-day historical coverage**. Caps are at most three candidates/month/source, eight/source for this run, 80 selected overall and 100 full-fetch attempts. Existing source/day canary budgets further constrained the run: nine selection deferrals, five fetch deferrals, one already-clustered candidate and two parsing/relevance rejections. Pending candidates were not all fetched or claimed as usable.

## Retrieval implementation

Migration `0032_document_evidence_tags` adds an indexed metadata table keyed by document, kind and value. Sector/topic tags describe article content; company tags require existing document identity or explicit mentions. The metadata backfill only tags this bounded batch: no existing embedding rebuild or whole-corpus reindex.

`research.search` uses three candidate groups: explicitly matched company evidence, sector evidence and broader requested macro/geopolitical topics. The latter groups do not inherit the company-symbol filter. Sector labels come from stored instrument classification and map to search families. PostgreSQL lexical retrieval and the existing local embedding model rank candidates, applying existing relevance/citation checks.

The tool defaults to five passages, allows ten, provides date/type/topic/sector filters and request/user-scoped pagination. It interleaves groups, deduplicates chunk IDs and limits each document to two passages across pages. Empty groups report their coverage; results do not imply complete market coverage. Public portfolio-scoped documents require portfolio ownership. Excluded documents are omitted from search and event sources.

Model-facing results contain passages, titles, dates, citation references and coverage. Full saved citations remain server-side. Duplicate quote snippets are removed from the provider payload after saving citations, and already-delivered passage text is omitted on repeat retrieval in the same execution. No model call is needed to tag or retrieve documents.

## Verification and commands

Local targeted regression: 66 tests passed across curated selection, retrieval, evidence pipeline, source breadth and Phase 8 read tools. A subsequent strengthened embedding-preservation check passed with the five retrieval tests. Tests cover date filters, ownership, company-only compatibility, cursor scope, page deduplication and saved citation quotes.

```bash
cd apps/api
DATABASE_URL='sqlite+pysqlite:///:memory:' EMBEDDING_BACKEND=hash \
  .venv/bin/python -m pytest app/tests/test_news_retrieval.py \
  app/tests/test_curated_news.py app/tests/test_evidence_pipeline_pass1.py \
  app/tests/test_evidence_pass4_breadth.py app/tests/test_phase8_phase1_read_tools.py -q
```

After approved source transfer, on Oracle:

```bash
cd /home/ubuntu/finance_project
docker compose -f compose.oracle.yml build api
docker compose -f compose.oracle.yml run --rm -T --no-deps api alembic upgrade head
docker compose -f compose.oracle.yml run --rm -T --no-deps api python -m app.jobs.tag_curated_news
docker compose -f compose.oracle.yml up -d --no-deps api
```

The ingestion command used a one-off allowlist and evidence-spool bind mount. To run another bounded batch deliberately:

```bash
docker compose -f compose.oracle.yml run --rm -T --no-deps \
  -e EVIDENCE_ENABLED=true -e EVIDENCE_PASS4_BREADTH_ENABLED=true \
  -e EVIDENCE_SOURCE_ALLOWLIST=world_fertilizer,world_cement,oilprice,cotton_grower,metalminer,semiconductor_engineering,freightwaves,guardian_world,medium_kahloon \
  -v /srv/psx/evidence-spool:/data/evidence-spool api \
  python -m app.jobs.curated_news --days 90 --max-selected 80 --per-source 8
```

Source/day limits apply and rerunning does not bypass them. Live producers were not enabled by this batch.

## Observed Oracle retrieval

A real LUCK query constrained to July 6 onward retrieved cement-industry financing/decarbonisation evidence and Hormuz/LNG/oil evidence whose documents have no LUCK symbol. Its company group was empty within that date range; no company evidence was fabricated. FFC retrieved two corporate briefings plus fertilizer security and Hormuz/LNG evidence, likewise without requiring FFC mentions in the broader documents.

The first one-off test required 16.166 seconds including local embedding model initialization; the following FFC retrieval took 215 ms. Returned passage text was 5,840 and 3,553 characters respectively. These are measured retrieval figures, not whole-chat latency or total model-input tokens.

Remaining limitations: selective historical coverage, small batch size, source/day deferrals, keyword-based tag selection and articles that qualify but may only indirectly affect Pakistan. Wider pre-existing documents have not all received new topic tags. This work proves evidence accessibility, not investment-advice quality; no live model synthesis was tested.

After API activation, unconstrained-history searches also retrieved the retained LUCK/FFC annual reports alongside the new sector/global articles. Warm retrieval measured 339 ms for LUCK and 432 ms for FFC. The complete model-facing tool results were 11,641 bytes and 9,898 bytes respectively, containing 6,736/5,240 passage characters. These byte counts include references and pagination metadata; they are not token counts. Both second pages returned five additional passages with zero repeated chunk IDs and zero excluded documents. Cold initialization again took approximately 16 seconds in the separate test process.
