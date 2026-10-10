"""Original-news discovery advances within the unchanged per-slot allowance."""
import json

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.evidence import DiscoveryCandidate, EvidenceSourceState
from app.providers.evidence.briefing_site import BASE, BriefingNewsSource
from app.services.evidence_operations import discover_stage
import pytest


def feed(count=8):
    return [
        {'headline': f'Synthetic Pakistan market story {index}',
         'summary': 'Unverified discovery summary.',
         'urls': [f'https://publisher.test/article-{index}'],
         'psx_impact_score': count-index}
        for index in range(count)
    ]


def adapter(rows):
    return BriefingNewsSource(fetcher=lambda *_args, **_kwargs:
        (json.dumps(rows).encode(), BASE+'/news.json', 'application/json', {}))


def urls(batch):
    return [candidate.canonical_url for candidate in batch.candidates]


def test_bounded_repeated_polls_reach_lower_ranked_originals():
    source = adapter(feed())
    cursor = {}
    observed = set()
    for _ in range(3):
        batch = source.discover_since(cursor, 3)
        assert len(batch.candidates) == 3
        observed.update(urls(batch))
        cursor = batch.next_cursor
    assert observed == {f'https://publisher.test/article-{index}' for index in range(8)}
    assert len(cursor['next_url_hash']) == 64


def test_cursor_survives_insertions_and_score_reordering():
    rows = feed()
    first = adapter(rows).discover_since({}, 3)
    rows.insert(0, {'headline': 'New story', 'urls': ['https://publisher.test/new'],
                    'psx_impact_score': 100})
    rows[-1]['psx_impact_score'] = 99
    second = adapter(rows).discover_since(first.next_cursor, 3)
    assert urls(second)[0] == 'https://publisher.test/article-3'
    assert len(set(urls(second))) == 3


def test_removed_cursor_story_restarts_at_current_top_story():
    rows = feed()
    first = adapter(rows).discover_since({}, 3)
    rows = [row for row in rows if row['urls'] != ['https://publisher.test/article-3']]
    second = adapter(rows).discover_since(first.next_cursor, 3)
    assert urls(second)[0] == 'https://publisher.test/article-0'


def test_original_url_metadata_and_publication_date_contract():
    rows = [{'headline': 'Synthesized discovery headline', 'summary': 'Not article text',
             'psx_impact_score': 9,
             'urls': [BASE+'/synthesized', 'https://publisher.test/article?utm_source=feed',
                      'https://publisher.test/article', 'http://localhost/private']}]
    batch = adapter(rows).discover_since({}, 6)
    assert urls(batch) == ['https://publisher.test/article']
    candidate = batch.candidates[0]
    assert candidate.published_at is None
    assert candidate.publisher == 'publisher.test'
    assert candidate.metadata['publication_date_basis'] == 'original_article_required'
    assert candidate.metadata['curation_impact_unverified'] == 9
    assert candidate.metadata['discovery_url'] == BASE+'/news.json'


def test_empty_and_zero_allowance_do_not_emit_candidates():
    assert not adapter([]).discover_since({}, 6).candidates
    assert not adapter(feed()).discover_since({}, 0).candidates
    assert len(adapter(feed(60)).discover_since({}, 100).candidates) == 50


@pytest.mark.usefixtures("database")
def test_discovery_stage_persists_rotation_without_increasing_slot_limit(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'pipeline_enabled', True)
    monkeypatch.setattr(settings, 'evidence_source_allowlist', 'briefing_news')
    source = adapter(feed())
    with SessionLocal() as db:
        results = [discover_stage(db, source, limit=3) for _ in range(3)]
        assert [result.new for result in results] == [3, 3, 2]
        assert all(result.discovered == 3 for result in results)
        assert db.scalar(select(func.count()).select_from(DiscoveryCandidate)) == 8
        state = db.scalar(select(EvidenceSourceState))
        assert json.loads(state.cursor_json)['next_url_hash']
