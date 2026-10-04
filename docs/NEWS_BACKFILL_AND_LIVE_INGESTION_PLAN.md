# News backfill and live ingestion — saved decisions, 2026-10-04

User-requested order: benchmark fixes → sourced stock-split fixes → live ingestion; UI can start without waiting for complete historical backfill.

## 1. Backfill actual history

- Use the existing dated archive adapters: Dawn/Guardian by day; FreightWaves, Cotton Grower, MetalMiner and Semiconductor Engineering in seven-day windows, following pagination until each window is exhausted.
- Save each window’s cursor in PostgreSQL so interruptions resume rather than restart.
- Rank titles/excerpts before downloading full articles, then validate the downloaded body/date.
- World Cement, World Fertilizer and OilPrice currently have verified RSS feeds—not verified historical archive adapters. Those need archive inspection first; RSS cannot recover their full history.

## 2. Select useful news consistently

- Move the selection used by curated_news.py into the shared discovery path in evidence_operations.py. Both historical and live articles then receive the same checks.
- Keep identifiable economic developments: supply disruptions, commodity prices, sector demand, earnings, policy changes, sanctions and trade restrictions.
- Reject tutorials, advertising, previews and undated content. Deduplicate URLs/content.
- Existing keyword rules are a first filter, not proof of investment relevance. Review accepted/rejected samples before expanding.

## 3. Run live ingestion

- Use the existing evidence-scheduler to poll feeds: the current configuration is 15 minutes for Guardian; 30 minutes for OilPrice/World Cement/World Fertilizer.
- Existing workers handle discover → fetch → parse → index. Allow two downloads concurrently but only one embedding/OCR job on Oracle.
- Give live articles priority over historical jobs.
- Adjust the tiny source/day caps using measured relevant arrivals and storage growth. Otherwise, frequent polling still produces very little usable news.
- Configure restart after crashes/reboots; the current ingestion services use restart: "no".

## 4. Prove it works

For each source, record last successful poll, new articles, rejection reasons, queued work and publication-to-searchable delay. Verify an actual newly published article becomes searchable—not merely that the worker is running.

AI receives the few passages retrieved for its question. No AI calls are needed for this ingestion path.

## Search responsibility

Recommendation: deterministic source discovery, relevance screening, deduplication and ingestion. The conversational model chooses bounded evidence searches and interprets retrieved evidence. No autonomous search agent or model call per ingested article is needed. Keyword filtering requires observed acceptance/rejection review, and cannot prove company impact.
