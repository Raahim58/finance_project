"""Small, ranked sector-news batches; immutable original articles, no LLM calls."""
import argparse
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from app.db.session import SessionLocal
from app.ingestion.evidence_catalog import build_pass1_registry
from app.ingestion.news_selection import classify_news
from app.providers.evidence.wordpress_archive import ARCHIVES, WordPressArchiveSource
from app.providers.evidence.dated_archive import DatedArchiveSource
from app.services.evidence_pipeline import ensure_source_config, persist_candidate
from app.services.evidence_operations import fetch_stage, parse_stage, index_stage

DEFAULT_SOURCES = ('world_fertilizer', 'world_cement', 'oilprice', 'cotton_grower',
    'metalminer', 'semiconductor_engineering', 'freightwaves', 'guardian_world', 'medium_kahloon')


def rank_candidates(candidates, start, end, per_month=3):
    seen, buckets = set(), {}
    for item in candidates:
        stamp = item.published_at
        listed_day = stamp.date() if stamp else date.fromisoformat(item.metadata['archive_date']) if item.metadata.get('archive_date') else None
        if listed_day is None or not start <= listed_day <= end:
            continue
        identity = item.canonical_url or item.observed_url
        if identity in seen:
            continue
        seen.add(identity)
        curation = classify_news(item.headline, str(item.metadata.get('summary') or ''))
        if not curation['eligible']:
            continue
        bucket = listed_day.strftime('%Y-%m')
        curation.update(date_from=str(start), date_to=str(end))
        buckets.setdefault(bucket, []).append(replace(item,
            metadata={**item.metadata, 'curated_news': curation, 'priority_class': 'historical'}))
    result = []
    for month in sorted(buckets, reverse=True):
        result.extend(sorted(buckets[month], key=lambda c: (-c.metadata['curated_news']['score'],
            -c.published_at.timestamp() if c.published_at else 0, c.observed_url))[:per_month])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append')
    parser.add_argument('--days', type=int, default=90, choices=range(1, 91))
    parser.add_argument('--max-selected', type=int, default=80, choices=range(1, 81))
    parser.add_argument('--per-source', type=int, default=8, choices=range(1, 11))
    args = parser.parse_args()
    end = datetime.now(UTC).date(); start = end - timedelta(days=args.days - 1)
    registry = build_pass1_registry(); plans = []
    for key in args.source or DEFAULT_SOURCES:
        source = registry.get(key); candidates = []
        try:
            candidates.extend(source.discover_since({}, 50).candidates)
            # Sample one recent week in each older month. This is deliberately
            # selective history, not a claim of complete daily archive coverage.
            if key in ARCHIVES:
                archive = WordPressArchiveSource(key)
                for age in (30, 60):
                    stop = end - timedelta(days=age); begin = max(start, stop - timedelta(days=6))
                    if begin <= stop:
                        candidates.extend(archive.discover_since({'date_from': str(begin),
                            'date_to': str(stop)}, 50).candidates)
            if key == 'guardian_world':
                archive = DatedArchiveSource(key)
                for age in (1, 30, 60):
                    day = end - timedelta(days=age)
                    if day >= start:
                        candidates.extend(archive.discover_since({'date_from': str(day)}, 50).candidates)
            ranked = rank_candidates(candidates, start, end)[:args.per_source]
            plans.append((source, ranked))
            print(json.dumps({'source':key,'discovered':len(candidates),'shortlisted':len(ranked)}), flush=True)
        except Exception as exc:
            print(json.dumps({'source':key,'error':type(exc).__name__,'detail':str(exc)[:400]}),flush=True)
    counts = {}; selected = fetched = 0
    with SessionLocal() as db:
        # Round-robin sources so a prolific feed cannot exhaust the batch.
        for offset in range(args.per_source):
            for source, candidates in plans:
                if offset >= len(candidates) or selected >= args.max_selected or fetched >= 100:
                    continue
                _, config, _ = ensure_source_config(db, source.key)
                candidate = candidates[offset]
                row, _ = persist_candidate(db, config, candidate); db.commit()
                result = fetch_stage(db, source, row.id); fetched += result.outcome == 'raw_ready'
                outcome = result.outcome
                if outcome == 'raw_ready':
                    result = parse_stage(db, source, row.id); outcome = result.outcome
                    if outcome == 'index_ready': outcome = index_stage(db, row.id).outcome
                selected += outcome == 'selected'
                counts[outcome] = counts.get(outcome, 0) + 1
                print(json.dumps({'source':source.key,'candidate':row.id,'title':candidate.headline,
                    'outcome':outcome}),flush=True)
    print(json.dumps({'selected':selected,'fetched':fetched,'outcomes':counts}),flush=True)


if __name__ == '__main__': main()
