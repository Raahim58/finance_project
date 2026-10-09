"""Saved company evidence must stop serving changed or disputed statements."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.pipeline import EvidenceStatement
from app.models.portfolio import Portfolio
from app.models.user import User
from app.models.workstation import FinancialFact, Instrument
from app.services.pipeline.intelligence import read, refresh
from app.services.pipeline.linking import link
from app.services.pipeline.parsing import sections
from app.services.pipeline.statements import extract
from app.services.rag_service import ParsedPage, create_document_from_pages
from app.ai.source_identity import source_identity

pytestmark = pytest.mark.usefixtures("database")


def prepare(db):
    instrument=Instrument(symbol='TEST',name='Test Company Limited',sector='Cement')
    db.add(instrument);db.flush()
    document=create_document_from_pages(db,[ParsedPage(1,'Test Company Limited announced a dividend.')],
        title='Dividend announcement',document_type='announcement',symbol='TEST',
        source_name='PSX Financials',source_url='https://example.com/dividend.pdf',
        published_date=date(2026,10,1),commit=False)
    sections(db,document.id);link(db,document.id);extract(db,document.id)
    refresh(db,instrument.id)
    statement=db.scalar(select(EvidenceStatement).where(EvidenceStatement.document_id==document.id,
        EvidenceStatement.event_type=='dividend'))
    assert statement is not None
    return instrument,document,statement


def dividend(db,instrument):
    return next(section for section in read(db,instrument.id) if section['section']=='dividends')


@pytest.mark.parametrize('review_state',['needs_review','rejected','disputed','superseded'])
def test_statement_review_invalidates_saved_evidence_without_document_change(review_state):
    with SessionLocal() as db:
        instrument,document,statement=prepare(db)
        before=dividend(db,instrument)
        original_hash=document.content_hash
        statement.validation_status=review_state;db.flush()
        after=dividend(db,instrument)
        assert document.content_hash==original_hash
        assert before['content']['evidence'] and before['sources']
        assert after['state']=='stale' and after['content']=={} and after['sources']==[]
        refresh(db,instrument.id)
        refreshed=dividend(db,instrument)
        assert refreshed['state']=='source_grounded'
        assert refreshed['content']['evidence']==[] and refreshed['sources']==[]


@pytest.mark.parametrize('field,value',[
    ('sentiment',{'direction':'negative','reason':'Reviewed interpretation changed'}),
    ('fingerprint','corrected-source-statement-version'),
    ('text','Test Company Limited has not announced a dividend.'),
    ('kind','management_claim'),
    ('lifecycle','proposed'),
    ('attribution','Test Company Limited'),
    ('topics',['dividends','governance']),
])
def test_statement_dependency_version_changes_invalidate_only_affected_section(field,value):
    with SessionLocal() as db:
        instrument,_,statement=prepare(db)
        before=dividend(db,instrument)
        setattr(statement,field,value);db.flush()
        assert dividend(db,instrument)['state']=='stale'
        assert next(s for s in read(db,instrument.id) if s['section']=='financial_performance')['state']=='source_grounded'
        refresh(db,instrument.id)
        refreshed=dividend(db,instrument)
        assert refreshed['state']=='source_grounded'
        assert refreshed['version']==before['version']+1
        if field=='sentiment':
            assert refreshed['content']['evidence'][0]['sentiment']==value
        original,=before['sources'];updated,=refreshed['sources']
        assert {key:updated[key] for key in ('statement_id','document_id','source_url','source_name','title')}=={
            key:original[key] for key in ('statement_id','document_id','source_url','source_name','title')}
        assert updated['quote_snippet']==statement.text
        assert source_identity(updated)!=source_identity(original)


def test_missing_statement_invalidates_saved_evidence():
    with SessionLocal() as db:
        instrument,_,statement=prepare(db)
        db.delete(statement);db.flush()
        assert dividend(db,instrument)['state']=='stale'


def test_unchanged_statement_keeps_version_and_original_citations():
    with SessionLocal() as db:
        instrument,_,_=prepare(db)
        before=dividend(db,instrument)
        refresh(db,instrument.id)
        assert dividend(db,instrument)==before


def test_prepared_statement_sources_keep_distinct_row_identities_and_exact_quotes():
    with SessionLocal() as db:
        instrument,document,statement=prepare(db)
        additional=EvidenceStatement(document_id=document.id,subject_type='instrument',subject_key=instrument.symbol,
            text='Fixture Company declared another dividend, subject to approval.',kind='management_claim',
            event_type='dividend',lifecycle='proposed',topics=['dividends'],sentiment={'direction':'unknown'},
            method='rules',extractor_version='fixture',fingerprint='distinct-statement',validation_status='validated')
        db.add(additional);db.flush();refresh(db,instrument.id)
        rows=dividend(db,instrument)['sources']
        assert len(rows)==2 and len({source_identity(row) for row in rows})==2
        assert {row['quote_snippet'] for row in rows}=={statement.text,additional.text}


@pytest.mark.parametrize('restriction',['visibility','owner_user_id','portfolio_id'])
def test_private_document_invalidates_and_cannot_reenter_public_intelligence(restriction):
    with SessionLocal() as db:
        instrument,document,_=prepare(db)
        user=User(email='private-source@example.com',password_hash='unused')
        db.add(user);db.flush()
        portfolio=Portfolio(user_id=user.id,name='Private portfolio')
        db.add(portfolio);db.flush()
        db.add(FinancialFact(instrument_id=instrument.id,taxonomy_key='revenue',
            value=Decimal('100'),unit='PKR',currency='PKR',period_type='annual',
            period_start=date(2025,7,1),period_end=date(2026,6,30),
            document_id=document.id,page_number=1,consolidated=True))
        db.flush();refresh(db,instrument.id)
        original_hash=document.content_hash
        private_value={'visibility':'private','owner_user_id':user.id,'portfolio_id':portfolio.id}[restriction]
        setattr(document,restriction,private_value);db.flush()
        assert document.content_hash==original_hash
        affected={s['section']:s for s in read(db,instrument.id)}
        for key in ('dividends','financial_performance'):
            assert affected[key]['state']=='stale'
            assert affected[key]['content']=={} and affected[key]['sources']==[]
        refresh(db,instrument.id)
        refreshed={s['section']:s for s in read(db,instrument.id)}
        for key in ('dividends','financial_performance'):
            assert refreshed[key]['state']=='source_grounded'
            assert refreshed[key]['content']['evidence']==[] and refreshed[key]['sources']==[]
