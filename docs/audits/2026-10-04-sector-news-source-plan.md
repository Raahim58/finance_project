# Sector news source checks and ingestion/retrieval plan

Checked from Oracle on 2026-10-04. These are read-only samples, not full coverage or activation claims. No language-model calls were used.

## Measured source access

| Source | Current discovery | One extracted article | Historical contract |
| --- | --- | --- | --- |
| World Fertilizer | /rss/worldfertilizer.xml | 2,194 characters, observed publication timestamp, article URL | Not yet verified |
| World Cement | /rss/worldcement.xml | 4,515 characters, observed publication timestamp, article URL | Not yet verified |
| OilPrice | /rss/main | 4,197 characters, observed publication timestamp, article URL | Not yet verified |
| Cotton Grower | /feed/ | 7,178 characters, observed publication timestamp, article URL | WordPress dated API returned two records for the January 2026 sample |
| MetalMiner | /feed/ | 8,166 characters, observed publication timestamp, article URL | January sample returned zero; not proof that historical coverage is absent or complete |
| Semiconductor Engineering | /feed/ | 1,714 characters, observed publication timestamp, article URL | WordPress dated API returned 25 records; publisher clock overlaps require UTC date filtering |
| FreightWaves | /feed | 7,505 characters, observed publication timestamp, article URL | WordPress dated API returned 46 records; publisher clock overlaps require UTC date filtering |
| gCaptain | /feed/ | 3,550 characters, observed publication timestamp, article URL | January API probe returned 403; earlier successful recent archive samples do not prove older access |
| EIA Today in Energy | /rss/todayinenergy.xml | 3,548 characters and timestamp, but extractor selected generic site title | Fix title extraction before treating its citation contract as accepted |
| LNG Prime | /feed/ | Only 200 characters, subscription preview | Exclude from full-text coverage |
| Fertilizer Daily | /feed/ | HTTP 403 | Exclude until a working public contract exists |
| Business Recorder generic latest feed | Existing RSS | Sample produced political article and homepage canonical URL | Use market/industry sections; validate canonical URL and article identity first |

World Fertilizer and World Cement publish dedicated category listings as well as RSS. Business Recorder has market, money/banking, cotton/textile, industry and company sections. Section listings need their own tested pagination/date contracts; no guessed section RSS URLs.

## Proposed scope after user redirected work toward sector-specific sources

1. Use Pakistan industry/company sections for domestic developments and specialist global sources for commodity inputs, demand, supply, trade and financing conditions. Retain a separate geopolitical lane. Do not treat a publisher as a company-impact classifier.
2. Prefer articles about demand, production, capacity, costs, trade restrictions, regulation, financing or company results. Exclude sports, local crime, promotional product notices and unrelated engineering papers. Store rejected reasons and audit samples of exclusions; keyword lists alone have demonstrated false negatives.
3. Preserve title, actual publication time, publisher, article URL, raw artifact hash, extracted text, multiple topic/sector tags and exact-name company mentions. Deduplicate before embedding. Separate observed source categories from inferred relevance tags. Numerical prices and financial series remain in structured tables.
4. Initial historical target: 12 months of useful sector and geopolitical evidence, newest periods first, with durable source/date/page cursors. Retrieve older structural evidence subsequently where public archives permit it. This is a target, not a claim that every source provides a year of accessible archives. RSS polling only supplies current entries.
5. Implement dated adapters first for verified archive APIs (Cotton Grower, Semiconductor Engineering and FreightWaves) and existing verified Guardian/Dawn dated listings. Verify World Fertilizer, World Cement, OilPrice and MetalMiner historical pagination before scheduling their older history. Recheck gCaptain's older-date 403 separately.
6. Current discovery polls approximately every 30 minutes, using conditional requests when supported. Historical workers remain bounded and resumable. Use one heavy indexing/OCR worker on Oracle; measure acceptance, date coverage, bytes and queue delay per source and sector before scaling.
7. Ingestion performs no generative-model calls. Article extraction, source metadata, deduplication and local embeddings are separate from chat. Shared AI digests can be designed later; they are not a prerequisite for collecting usable evidence.
8. At question time, query exact numerical data separately. Retrieve by question, companies, sectors, relevant economic topics and requested dates; combine sector/company material with relevant macro/geopolitical evidence rather than restricting to exact company mentions. Rank excerpts, collapse duplicate coverage, and retain source citations. Return a small first result page; the assistant can read further relevant articles or older periods using existing budgets. Never send the entire archive to the model.
9. Example, not a new token ceiling: six excerpts of roughly 500 tokens consume about 3,000 news tokens even if the library contains 100,000 articles. Deeper comparisons can retrieve more. Existing chat limits remain unchanged.

## Current execution state

Broad backfill expansion was paused at the user's request to clarify source selection and architecture. Newly probed sector feeds have not been registered or activated. Existing ingestion changes and approved Oracle transfers remain in place; continuous news workers have not been started in this continuation. No corpus-wide reindexing is required for newly ingested articles: they are indexed once when accepted. Existing-document metadata corrections must be scoped separately.

No migration is required for these read-only checks. Implementation changes and commands will be documented after the source contracts and scope are finalized.
