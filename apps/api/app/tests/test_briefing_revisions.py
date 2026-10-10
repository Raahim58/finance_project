"""Dated research revisions remain interpretation with retained provenance."""
from datetime import date
import json

from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.document import Citation, Document
from app.models.workstation import FinancialFact, Instrument
from app.services.pipeline.briefing import URL, capture, read
from app.services.rag_service import ParsedPage, create_document_from_pages
import pytest

pytestmark = pytest.mark.usefixtures("database")


def payload(generated='2026-10-07T09:00:00+05:00', *, reason='Synthetic original interpretation'):
    return {'generated_at_pkt': generated, 'research_note': {
        'title': 'Synthetic morning commentary', 'executive_summary': 'Synthetic market interpretation.',
        'sector_highlights': [
            {'sector': 'Cement', 'outlook': 'uncertain', 'bullets': ['Synthetic cement interpretation.']},
            {'sector': 'Fertilizer', 'outlook': 'uncertain', 'bullets': ['Synthetic fertilizer interpretation.']}],
        'stocks_to_watch': [
            {'ticker': 'LUCK', 'reason': reason},
            {'ticker': 'LUCK', 'reason': 'A distinct synthetic LUCK section.'},
            {'ticker': 'FFC', 'reason': 'A distinct synthetic FFC interpretation.'}]}}


def ingest(db, value):
    raw=json.dumps(value).encode()
    return capture(db,fetcher=lambda *_args,**_kwargs:(raw,URL,'application/json',{}))


def prepare(db,monkeypatch,tmp_path):
    monkeypatch.setattr(settings,'source_artifact_root',str(tmp_path))
    db.add_all([Instrument(symbol='LUCK',name='Lucky Cement Limited',sector='Cement'),
        Instrument(symbol='FFC',name='Fauji Fertilizer Company',sector='Fertilizer')])
    db.flush()


def test_same_timestamp_correction_supersedes_old_edition_and_preserves_all_sections(monkeypatch,tmp_path):
    with SessionLocal() as db:
        prepare(db,monkeypatch,tmp_path)
        old=ingest(db,payload());db.commit()
        new=ingest(db,payload(reason='Synthetic corrected interpretation'));db.commit()
        assert len(old['document_ids'])==len(new['document_ids'])==6
        assert all(db.get(Document,identifier).status=='superseded' for identifier in old['document_ids'])
        rows=read(db,limit=20)
        assert {row['id'] for row in rows}==set(new['document_ids'])
        assert len([row for row in rows if row['symbol']=='LUCK'])==2
        assert any(row['symbol']=='FFC' for row in rows)
        assert {row['sector'] for row in rows if row['symbol'] is None}=={None,'Cement','Fertilizer'}
        assert all(row['published_date']=='2026-10-07' and row['generated_at']=='2026-10-07T04:00:00+00:00' for row in rows)
        assert all(row['artifact_id'] and row['json_pointer'] and row['source_url']==URL for row in rows)
        assert db.scalar(select(func.count()).select_from(FinancialFact))==0


def test_replaying_known_old_artifact_does_not_resurrect_superseded_interpretation(monkeypatch,tmp_path):
    with SessionLocal() as db:
        prepare(db,monkeypatch,tmp_path)
        original=payload();old=ingest(db,original);db.commit()
        new=ingest(db,payload(reason='Synthetic correction'));db.commit()
        replay=ingest(db,original);db.commit()
        assert replay['document_ids']==old['document_ids']
        assert {row['id'] for row in read(db,limit=20)}==set(new['document_ids'])
        assert db.scalar(select(func.count()).select_from(Document))==12


def test_out_of_order_older_generation_cannot_replace_newer_company_or_sector(monkeypatch,tmp_path):
    with SessionLocal() as db:
        prepare(db,monkeypatch,tmp_path)
        new=ingest(db,payload('2026-10-07T11:00:00+05:00',reason='Synthetic latest view'));db.commit()
        old=ingest(db,payload('2026-10-07T09:00:00+05:00'));db.commit()
        assert all(db.get(Document,identifier).status=='superseded' for identifier in old['document_ids'])
        assert {row['id'] for row in read(db,limit=20)}==set(new['document_ids'])


def test_latest_selection_keeps_earlier_dated_history_and_distinct_filtered_sections(monkeypatch,tmp_path):
    with SessionLocal() as db:
        prepare(db,monkeypatch,tmp_path)
        historical=ingest(db,payload('2026-10-06T09:00:00+05:00'));db.commit()
        latest=ingest(db,payload());db.commit()
        assert all(db.get(Document,identifier).status=='parsed' for identifier in historical['document_ids'])
        assert {row['id'] for row in read(db,limit=20)}==set(latest['document_ids'])
        rows=read(db,symbols=['LUCK'],sectors=['Cement'],limit=20)
        assert len(rows)==3
        assert len([row for row in rows if row['symbol']=='LUCK'])==2
        assert any(row['symbol'] is None and row['sector']=='Cement' for row in rows)


def test_commentary_revisions_leave_original_article_citations_unchanged(monkeypatch,tmp_path):
    with SessionLocal() as db:
        prepare(db,monkeypatch,tmp_path)
        article=create_document_from_pages(db,[ParsedPage(1,'Synthetic original publisher article evidence.')],
            title='Original publisher article',document_type='news',source_name='Original publisher',
            source_url='https://publisher.test/original',published_date=date(2026,10,7),physical_pages=False,commit=False)
        citation=db.scalar(select(Citation).where(Citation.document_id==article.id))
        identity=(citation.id,citation.source_url,citation.quote_snippet,citation.page_number)
        ingest(db,payload());ingest(db,payload(reason='Synthetic correction'));db.commit()
        db.refresh(citation)
        assert (citation.id,citation.source_url,citation.quote_snippet,citation.page_number)==identity
        assert db.get(Document,article.id).status=='parsed'
