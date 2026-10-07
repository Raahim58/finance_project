"""Discovery/outbox atomicity and deployed cursor/artifact-pin regressions."""
from datetime import UTC, date, datetime, timedelta
import json

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.evidence import Candidate, DiscoveryBatch
from app.models.evidence import DiscoveryCandidate
from app.models.pipeline import ArtifactPin, IngestionStageRun
from app.models.workstation import DataSource, Instrument, SourceArtifact
from app.services.evidence_operations import discover_stage
from app.services.evidence_pipeline import ensure_source_config
from app.services.pipeline import runs
from app.services.pipeline.intelligence import refresh
from app.services.pipeline.linking import link
from app.services.pipeline.parsing import sections
from app.services.pipeline.statements import extract
from app.services.rag_service import ParsedPage, create_document_from_pages


class DiscoveryFixture:
    key = 'mettis'

    def discover_since(self, cursor, limit):
        candidate = Candidate(source_key=self.key,
            observed_url='https://mettisglobal.news/synthetic-recovery-story',
            headline='Synthetic Pakistan market recovery story', publisher='Mettis',
            discovered_at=datetime.now(UTC), discovery_method='fixture')
        return DiscoveryBatch((candidate,), {'synthetic_cursor': 'advanced'})


def test_pipeline_successor_failure_rolls_back_candidates_cursor_and_recovers(monkeypatch):
    from app.ingestion.evidence_catalog import build_pass1_registry
    from app.jobs.pipeline_tasks import perform
    monkeypatch.setattr(settings, 'pipeline_enabled', True)
    monkeypatch.setattr(settings, 'evidence_source_allowlist', 'mettis')
    registry = build_pass1_registry()
    monkeypatch.setattr(registry, 'get', lambda _key: DiscoveryFixture())
    monkeypatch.setattr('app.ingestion.evidence_catalog.build_pass1_registry', lambda: registry)
    with SessionLocal() as db:
        _, _, state = ensure_source_config(db, 'mettis')
        state.cursor_json = '{"synthetic_cursor":"original"}'
        row = runs.enqueue(db, 'discover', 'canary:fixture:source',
            {'source_key': 'mettis', 'news_limit': 1, 'canary_batch': 'fixture'})
        db.commit()
        identifier, state_id = row.id, state.id
        token = runs.claim(db, identifier)
        output, children = perform(db, db.get(IngestionStageRun, identifier))
        assert output['new'] == 1 and len(children) == 1
        def successor_crash(*_args, **_kwargs):
            raise RuntimeError('synthetic_successor_failure')
        with monkeypatch.context() as scoped:
            scoped.setattr(runs, 'enqueue', successor_crash)
            with pytest.raises(RuntimeError, match='synthetic_successor_failure'):
                runs.finish(db, identifier, token, output, children=children)
        db.rollback()
        assert db.scalar(select(func.count()).select_from(DiscoveryCandidate)) == 0
        from app.models.evidence import EvidenceSourceState
        assert json.loads(db.get(EvidenceSourceState, state_id).cursor_json) == {'synthetic_cursor': 'original'}
        runs.fail(db, identifier, token, 'synthetic_successor_failure')
        token = runs.claim(db, identifier, now=datetime.now(UTC)+timedelta(minutes=1))
        assert token
        output, children = perform(db, db.get(IngestionStageRun, identifier))
        runs.finish(db, identifier, token, output, children=children)
        assert db.scalar(select(func.count()).select_from(DiscoveryCandidate)) == 1
        child = db.scalar(select(IngestionStageRun).where(IngestionStageRun.stage == 'fetch'))
        assert child and child.status == 'queued'
        assert child.subject_key.startswith('canary:fixture:')
        assert child.input['canary_batch'] == 'fixture'
        assert json.loads(db.get(EvidenceSourceState, state_id).cursor_json) == {'synthetic_cursor': 'advanced'}


def test_historical_cursor_override_preserves_live_discovery_cursor(monkeypatch):
    monkeypatch.setattr(settings, 'evidence_source_allowlist', 'mettis')
    with SessionLocal() as db:
        _, _, state = ensure_source_config(db, 'mettis')
        state.cursor_json = '{"synthetic_cursor":"live"}'
        db.commit()
        result = discover_stage(db, DiscoveryFixture(), limit=1,
            priority_class='historical', cursor_override={'synthetic_cursor': 'history'})
        assert result.next_cursor == {'synthetic_cursor': 'advanced'}
        db.refresh(state)
        assert json.loads(state.cursor_json) == {'synthetic_cursor': 'live'}


def test_multiple_statements_from_one_artifact_insert_only_one_section_pin():
    with SessionLocal() as db:
        issuer = Instrument(symbol='LUCK', name='Lucky Cement Limited', sector='Cement')
        source = DataSource(name='Synthetic official fixture', source_type='evidence')
        db.add_all([issuer, source]); db.flush()
        artifact = SourceArtifact(data_source_id=source.id, source_url='https://publisher.test/fixture.pdf',
            sha256='a'*64, parser_version='fixture', content_type='application/pdf')
        db.add(artifact); db.flush()
        document = create_document_from_pages(db, [ParsedPage(1,
            'Lucky Cement Limited announced a dividend. Lucky Cement Limited declared another dividend.')],
            title='LUCK synthetic announcement', document_type='announcement', symbol='LUCK',
            source_name='PSX Financials', source_url=artifact.source_url, artifact_id=artifact.id,
            published_date=date(2026, 10, 1), commit=False)
        sections(db, document.id); link(db, document.id)
        assert len(extract(db, document.id)) == 2
        ids = refresh(db, issuer.id)
        db.flush()
        assert db.scalar(select(func.count()).select_from(ArtifactPin)) == 1
        assert refresh(db, issuer.id) == ids
        db.flush()
        assert db.scalar(select(func.count()).select_from(ArtifactPin)) == 1
