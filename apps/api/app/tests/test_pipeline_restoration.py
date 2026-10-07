"""Critical restart, provenance, classification, time and capacity contracts."""
from datetime import UTC,date,datetime,timedelta
from decimal import Decimal
import json
import pytest
from sqlalchemy import func,select
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.document import Document,DocumentChunk
from app.models.pipeline import IngestionStageRun,SourceTarget,DocumentSection,EvidenceStatement,CompanyIntelligenceSection,IntelligenceDependency,StatementEvidence
from app.models.workstation import Instrument,ExchangeCalendarDay,FinancialFact
from app.services.pipeline import runs
from app.services.pipeline.parsing import sections
from app.services.pipeline.linking import link
from app.services.pipeline.statements import extract,labels,validate_candidate
from app.services.pipeline.intelligence import refresh,read
from app.services.pipeline.scheduling import price_bucket,scheduled_bucket
from app.services.rag_service import create_document_from_pages,ParsedPage,search_rag
from app.schemas.rag import RagSearchRequest
from app.schemas.pipeline import StatementCandidate


def seed(db, *, kind='announcement',body=None):
    inst=Instrument(symbol='LUCK',name='Lucky Cement Limited',sector='Cement');db.add(inst);db.flush()
    text=body or 'Lucky Cement Limited announced a dividend. Management expects the expansion to increase capacity. However, no binding commitment was made.'
    doc=create_document_from_pages(db,[ParsedPage(1,text)],title='LUCK announcement',document_type=kind,symbol='LUCK',source_name='PSX Financials',source_url='https://financials.psx.com.pk/a.pdf',published_date=date(2026,10,1),commit=False)
    return inst,doc


def test_duplicate_enqueue_single_claim_and_stale_completion():
    with SessionLocal() as db:
        first=runs.enqueue(db,'sections','doc:1',{'document_id':'one'})
        duplicate=runs.enqueue(db,'sections','doc:1',{'document_id':'one'});db.commit()
        assert first.id==duplicate.id
        token=runs.claim(db,first.id);assert token
        assert runs.claim(db,first.id) is None
        with pytest.raises(RuntimeError,match='stale_stage_lease'): runs.finish(db,first.id,'wrong',{})
        db.rollback()
        runs.finish(db,first.id,token,{'parsed':True},children=[('link','doc:1',{'document_id':'one'})])
        assert db.scalar(select(func.count()).select_from(IngestionStageRun))==2
        assert runs.claim(db,first.id) is None


def test_worker_loss_recovered_and_old_fencing_token_rejected():
    with SessionLocal() as db:
        row=runs.enqueue(db,'sections','doc:1',{'document_id':'one'});db.commit()
        token=runs.claim(db,row.id,now=datetime.now(UTC)-timedelta(minutes=10))
        assert runs.recover(db)==1
        fresh=runs.claim(db,row.id);assert fresh and fresh!=token
        with pytest.raises(RuntimeError): runs.finish(db,row.id,token,{})
        db.rollback();runs.finish(db,row.id,fresh,{})


def test_queue_publish_loss_recovers_without_duplicate_work():
    with SessionLocal() as db:
        row=runs.enqueue(db,'sections','doc:1',{'document_id':'one'});db.commit()
        now=datetime.now(UTC)
        def broken(*args): raise ConnectionError('offline')
        assert runs.dispatch(db,broken,now=now)==0
        sent=[]
        assert runs.dispatch(db,lambda *args:sent.append(args),now=now+timedelta(seconds=30))==0
        assert runs.dispatch(db,lambda *args:sent.append(args),now=now+timedelta(seconds=61))==1
        assert sent[0][0]==row.id


def test_dispatch_reserves_history_capacity():
    with SessionLocal() as db:
        for i in range(20): runs.enqueue(db,'sections',str(i),{'document_id':str(i)})
        for i in range(5): runs.enqueue(db,'sections','h'+str(i),{'document_id':'h'+str(i)},mode='historical')
        db.commit();sent=[];runs.dispatch(db,lambda *args:sent.append(args),limit=10)
        assert sum(mode=='historical' for _,_,mode in sent)==2


def test_sections_linking_and_statement_replay_preserve_quotes():
    with SessionLocal() as db:
        inst,doc=seed(db);first=sections(db,doc.id);assert sections(db,doc.id)[0].id==first[0].id
        assert link(db,doc.id)==[inst.id]
        assert link(db,doc.id)==[inst.id]
        first=extract(db,doc.id);second=extract(db,doc.id);assert first==second
        rows=list(db.scalars(select(EvidenceStatement)))
        assert any(row.kind=='guidance' for row in rows)
        assert all(row.text in db.get(DocumentSection,db.scalar(select(StatementEvidence.section_id).where(StatementEvidence.statement_id==row.id))).text for row in rows)
        assert all(row.sentiment['direction']=='unknown' for row in rows)


@pytest.mark.parametrize('quote,kind,lifecycle',[
    ('Management expects profit to increase.','guidance','unknown'),
    ('Sources said an unconfirmed acquisition is proposed.','rumor','proposed'),
    ('The consortium submitted an EOI for due diligence; no binding commitment exists.','reported_fact','proposed'),
    ('The plant was commissioned.','reported_fact','completed'),
])
def test_classification_preserves_uncertainty(quote,kind,lifecycle):
    assert labels(quote,official=True)[::2]==(kind,lifecycle)


def test_model_cannot_promote_guidance_or_invent_quotes():
    with SessionLocal() as db:
        inst,doc=seed(db);parts=sections(db,doc.id);section=parts[0]
        candidate=StatementCandidate(section_id=section.id,subject_key='LUCK',quote='Management expects the expansion to increase capacity.',kind='reported_fact',event_type='expansion',lifecycle='completed',topics=[],attribution=None,sentiment=None)
        with pytest.raises(ValueError,match='claim_promoted'): validate_candidate(candidate,{section.id:section},{'LUCK'},official=True)
        candidate.quote='Invented claim.'
        with pytest.raises(ValueError,match='quote_not_in_source'): validate_candidate(candidate,{section.id:section},{'LUCK'},official=True)


def test_one_invalid_model_candidate_writes_nothing():
    with SessionLocal() as db:
        _,doc=seed(db);part=sections(db,doc.id)[0];link(db,doc.id)
        valid={'section_id':part.id,'subject_key':'LUCK','quote':'Lucky Cement Limited announced a dividend.',
            'kind':'reported_fact','event_type':'dividend','lifecycle':'announced','topics':[],'attribution':None,'sentiment':None}
        with pytest.raises(ValueError): extract(db,doc.id,model_output={'statements':[valid,dict(valid,quote='Invented statement.')]})
        assert db.scalar(select(func.count()).select_from(EvidenceStatement))==0


def test_intelligence_unchanged_reused_exact_values_and_withdrawal():
    with SessionLocal() as db:
        inst,doc=seed(db);sections(db,doc.id);link(db,doc.id);extract(db,doc.id)
        fact=FinancialFact(instrument_id=inst.id,taxonomy_key='revenue',value=Decimal('279367000000'),unit='PKR',currency='PKR',period_type='annual',period_start=date(2025,7,1),period_end=date(2026,6,30),document_id=doc.id,page_number=7,consolidated=True)
        db.add(fact);db.flush()
        ids=refresh(db,inst.id);assert refresh(db,inst.id)==ids
        financial=next(s for s in read(db,inst.id) if s['section']=='financial_performance')
        assert Decimal(financial['content']['evidence'][0]['value'])==Decimal('279367000000')
        assert financial['content']['evidence'][0]['period_start']=='2025-07-01'
        doc.status='revoked';db.flush()
        assert next(s for s in read(db,inst.id) if s['section']=='dividends')['state']=='stale'
        refresh(db,inst.id)
        assert not next(s for s in read(db,inst.id) if s['section']=='financial_performance')['content']['evidence']


@pytest.mark.parametrize('value,expected',[
    ('2026-10-06T09:31:00+05:00',False),('2026-10-06T09:32:00+05:00',True),
    ('2026-10-06T15:30:00+05:00',False),('2026-10-09T11:00:00+05:00',True),
    ('2026-10-09T12:00:00+05:00',False),('2026-10-09T14:31:00+05:00',False),
    ('2026-10-09T14:32:00+05:00',True),('2026-10-09T16:30:00+05:00',False),
    ('2026-10-10T10:00:00+05:00',False),('2026-10-06T22:00:00+05:00',False),
])
def test_only_regular_session_price_polling(value,expected):
    with SessionLocal() as db: assert bool(price_bucket(db,datetime.fromisoformat(value))[0])==expected


def test_calendar_override_holiday_and_friday_break():
    with SessionLocal() as db:
        db.add(ExchangeCalendarDay(exchange_code='PSX',session_date=date(2026,10,6),is_session=False,status='observed'));db.flush()
        assert price_bucket(db,datetime.fromisoformat('2026-10-06T10:00:00+05:00'))[0] is None
        db.add(ExchangeCalendarDay(exchange_code='PSX',session_date=date(2026,10,9),is_session=True,status='observed',session_windows=[['10:00','11:00']]));db.flush()
        assert price_bucket(db,datetime.fromisoformat('2026-10-09T14:40:00+05:00'))[0] is None


def test_requested_news_and_announcement_slots():
    with SessionLocal() as db:
        for hour in (10,14,21):
            now=datetime(2026,10,6,hour,1,tzinfo=__import__('zoneinfo').ZoneInfo('Asia/Karachi'))
            assert datetime.fromisoformat(scheduled_bucket('news',now,db)).hour==hour
        assert datetime.fromisoformat(scheduled_bucket('announcements',now,db)).hour==18


def test_unembedded_history_is_lexically_searchable_and_revoked_is_not():
    with SessionLocal() as db:
        _,doc=seed(db,kind='news',body='Lucky Cement Limited capacity expansion and dividend announcement. '*10)
        for chunk in db.scalars(select(DocumentChunk).where(DocumentChunk.document_id==doc.id)):
            chunk.embedding_vector=None;chunk.embedding_json='[]';chunk.embedding_status='lexical_only'
        db.flush()
        result=search_rag(db,None,RagSearchRequest(query='LUCK capacity dividend',symbols=['LUCK']))
        assert result.chunks
        doc.status='revoked';db.flush()
        assert not search_rag(db,None,RagSearchRequest(query='LUCK capacity dividend',symbols=['LUCK'])).chunks


def test_entity_alias_does_not_crosslink_ambiguous_name():
    from app.models.workstation import InstrumentAlias
    with SessionLocal() as db:
        first,doc=seed(db,body='Ambiguous Group announces a dividend.')
        second=Instrument(symbol='OTHER',name='Other Limited');db.add(second);db.flush()
        for inst in (first,second): db.add(InstrumentAlias(instrument_id=inst.id,provider='fixture',alias='Ambiguous Group'))
        db.flush();sections(db,doc.id);assert link(db,doc.id)==[]


def test_unknown_fiscal_calendar_does_not_invent_dates():
    from app.providers.fundamentals.dps_standardized import _period
    assert _period('2026')[1] is None
    assert _period('Q3 2026',6)[1]==date(2026,3,31)
    assert _period('Q1 2026',6)[1]==date(2025,9,30)
    assert _period('2026',6)[1]==date(2026,6,30)
    assert _period('Q3 2026',12)[1]==date(2026,9,30)


def test_free_router_fails_closed_on_price_and_schema():
    from app.services.pipeline.enrichment import MODELS,verified_free_model,request_payload
    row={'id':MODELS[0],'pricing':{'prompt':'0','completion':'0'},'supported_parameters':['response_format','structured_outputs']}
    assert verified_free_model({'data':[row]},MODELS[0])==row
    with pytest.raises(ValueError): verified_free_model({'data':[dict(row,pricing={'prompt':'0.01','completion':'0'})]},MODELS[0])
    with pytest.raises(ValueError): verified_free_model({'data':[dict(row,supported_parameters=[])]},MODELS[0])
    payload=request_payload(MODELS[0],[{'section_id':'s','text':'Capacity increased.'}],['LUCK'])
    assert payload['provider']['max_price']=={'prompt':0,'completion':0}
    assert payload['response_format']['json_schema']['strict']
    with pytest.raises(ValueError): request_payload('paid/default',[],[])


def test_capacity_missing_volume_defers_without_deleting(tmp_path,monkeypatch):
    from app.services.pipeline.retention import capacity
    with SessionLocal() as db:
        assert capacity(db,root=tmp_path/'absent')['allow_live'] is False
        monkeypatch.setattr(settings,'pipeline_min_free_gib',1000000)
        assert capacity(db,root=tmp_path)['allow_history'] is False
        assert db.scalar(select(func.count()).select_from(Document))==0


def test_continuous_history_ignores_daily_quotas_but_live_stays_bounded(monkeypatch):
    from app.services.pipeline.retention import daily_allowance
    now = datetime.now(UTC)
    monkeypatch.setattr(settings, 'pipeline_max_history_pdfs', 0)
    monkeypatch.setattr(settings, 'pipeline_max_history_articles', 0)
    monkeypatch.setattr(settings, 'pipeline_max_history_mib', 0)
    monkeypatch.setattr(settings, 'pipeline_max_live_articles', 1)
    with SessionLocal() as db:
        for stage, mode in [('report_fetch', 'historical'), ('fetch', 'historical'), ('fetch', 'live')]:
            for i in range(30):
                row = runs.enqueue(db, stage, f'{stage}:{mode}:{i}', {}, mode=mode)
                row.status = 'completed'; row.heartbeat_at = now
        db.flush()
        from types import SimpleNamespace
        assert daily_allowance(db, SimpleNamespace(mode='historical'), is_pdf=True, now=now)
        assert daily_allowance(db, SimpleNamespace(mode='historical'), now=now)
        assert not daily_allowance(db, SimpleNamespace(mode='live'), now=now)


def test_document_worker_chain_is_replayable_without_models(monkeypatch):
    from app.jobs.pipeline_tasks import execute
    monkeypatch.setattr(settings,'pipeline_enabled',True)
    with SessionLocal() as db:
        inst,doc=seed(db);run=runs.enqueue(db,'sections','document:'+doc.id,{'document_id':doc.id});db.commit()
        identifier=run.id;instrument_id=inst.id
    execute(identifier)
    for _ in range(10):
        with SessionLocal() as db:
            next_run=db.scalar(select(IngestionStageRun).where(IngestionStageRun.status=='queued'))
            if not next_run: break
            identifier=next_run.id
        execute(identifier)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(CompanyIntelligenceSection).where(CompanyIntelligenceSection.instrument_id==instrument_id))==8
        assert not db.scalar(select(IngestionStageRun.id).where(IngestionStageRun.status.in_(('queued','running','dead_letter'))))


def test_scheduler_slot_commits_once_and_never_publishes_prices_at_night():
    from app.jobs.pipeline_scheduler import schedule_sources
    from app.services.ingestion_persistence import source
    with SessionLocal() as db:
        publisher=source(db,'Fixture source','evidence','https://source.test',1,60,'fixture')
        for adapter,schedule in (('dawn','news'),('prices','prices')):
            db.add(SourceTarget(data_source_id=publisher.id,scope_key=adapter,adapter_key=adapter,schedule=schedule,enabled=True))
        db.commit()
        now=datetime.fromisoformat('2026-10-06T21:05:00+05:00')
        assert schedule_sources(db,now)==1
        assert schedule_sources(db,now)==0
        assert not db.scalar(select(IngestionStageRun).where(IngestionStageRun.stage=='prices'))


def test_mettis_archive_uses_rowid_not_article_news_id():
    from app.providers.evidence.mettis_archive import MettisArchiveSource
    observed={'rowid':99,'newsID':5000,'headings':{'heading':['Lucky Cement expansion']},
        'descriptions':{'description':['Capacity increases']},'link':'Lucky-Cement-expansion-5000','publishedTime':'2026-09-30T10:00:00'}
    def fetch(url,params=None):
        assert params=={'lastNewsID':100}
        return json.dumps([observed]).encode(),url,'application/json',{}
    adapter=MettisArchiveSource(cursor={'last_news_id':100},fetcher=fetch)
    batch=adapter.discover_since({},50)
    assert batch.next_cursor['last_news_id']==99
    assert batch.candidates[0].headline=='Lucky Cement expansion'
    assert batch.candidates[0].published_at is None
    assert batch.candidates[0].metadata['publication_date_hint']=='2026-09-30'
    with pytest.raises(ValueError,match='cursor_not_monotone'):
        MettisArchiveSource(cursor={'last_news_id':99},fetcher=lambda *a,**kw:(json.dumps([observed]).encode(),'u','json',{})).discover_since({},50)


def test_tavily_discovers_allowlisted_urls_without_generating_answers():
    import httpx
    from app.providers.evidence.tavily import TavilyDiscoverySource
    def handler(request):
        payload=json.loads(request.content)
        assert payload['include_answer'] is False and payload['include_raw_content'] is False
        assert payload['search_depth']=='basic' and payload['auto_parameters'] is False
        return httpx.Response(200,json={'results':[{'url':'https://mettisglobal.news/article','title':'Article','content':'Search snippet'},
            {'url':'https://untrusted.test/article','title':'Wrong host'}]})
    adapter=TavilyDiscoverySource(api_key='offline-fixture',query='LUCK expansion',domains=['mettisglobal.news'],transport=httpx.MockTransport(handler))
    batch=adapter.discover_since({},5)
    assert len(batch.candidates)==1
    assert 'Search snippet' not in json.dumps(batch.candidates[0].metadata)


def test_citation_identity_survives_tool_presentation_changes():
    from app.ai.tool_loop import _attach_evidence
    checkpoint={'evidence':{},'next_evidence':1}
    first=_attach_evidence(checkpoint,{'sources':[{'id':'one','chunk_id':'chunk1','document_id':'doc1','title':'Original','quote_snippet':'Exact quote'}]})
    second=_attach_evidence(checkpoint,{'sources':[{'id':'other','chunk_id':'chunk1','document_id':'doc1','title':'Original','quote_snippet':'Exact quote','published_at':'2026-10-01'}]})
    assert first['sources'][0]['evidence_ref']==second['sources'][0]['evidence_ref']
    assert len(checkpoint['evidence'])==1
    assert checkpoint['evidence']['E1']['source']['quote_snippet']=='Exact quote'


def test_catalog_schemas_loaded_only_on_demand(monkeypatch):
    from app.ai.tool_loop import _catalog,_sync_tool
    from app.ai.providers.base import ContentBlock
    monkeypatch.setattr(settings,'pipeline_enabled',False);old=_catalog()
    monkeypatch.setattr(settings,'pipeline_enabled',True);compact=_catalog()
    assert len(compact)<len(old)
    assert any(t.name=='tools.catalog' for t in compact)
    name=next(t.name for t in old if t.name not in {v.name for v in compact})
    result=_sync_tool('fixture',ContentBlock('tool_call',name='tools.catalog',arguments={'names':[name]}))
    from app.tools.registry import expand_model_data
    loaded=expand_model_data(result['data'])['loaded_tools']
    assert name in {t.name for t in _catalog(selected=loaded)}


def test_request_diagnostics_contain_counts_only():
    from app.ai.token_counting import payload_breakdown
    value=payload_breakdown('fixture',{'messages':[{'role':'user','content':'private-example-not-for-export'}],'tools':[]})
    assert value['serialized_bytes']>0
    assert 'private-example-not-for-export' not in json.dumps(value)


def test_strict_financial_extraction_preserves_basis_duration_and_scale():
    from app.providers.fundamentals.extraction import FinancialPage,extract_facts,explicit_report_period
    text="Unconsolidated Statement of Profit or Loss\nFor the six months ended December 31, 2024\nAmounts in PKR '000\n2024 2023\nRevenue 279367000 200000000"
    pages=[FinancialPage(7,text)];period=explicit_report_period(pages)
    assert period==date(2024,12,31)
    facts,_=extract_facts(pages,period,strict=True)
    assert facts[0].value==Decimal('279367000000')
    assert facts[0].period_start==date(2024,7,1) and facts[0].period_end==date(2024,12,31)
    assert facts[0].consolidated is False
    unknown=[FinancialPage(7,text.replace('Unconsolidated ',''))]
    assert extract_facts(unknown,period,strict=True)[0]==[]
    assert explicit_report_period([FinancialPage(1,'Annual report FY2026')],'LUCK annual report 2026') is None


def test_new_statement_events_reach_existing_company_consumers():
    from app.services.pipeline.events import build
    from app.services.research_intelligence_service import event_views
    from app.schemas.event_intelligence import NormalizedEventResponse
    with SessionLocal() as db:
        inst,doc=seed(db);sections(db,doc.id);link(db,doc.id);extract(db,doc.id)
        result=build(db,doc.id);assert result['events']
        assert build(db,doc.id)==result
        rows=event_views(db,symbol=inst.symbol)
        assert rows and rows[0]['statement_kind'] in ('reported_fact','guidance')
        assert rows[0]['source_document_type']=='announcement'
        NormalizedEventResponse.model_validate(rows[0])


def test_html_citations_have_offsets_and_no_fabricated_pages():
    from app.models.document import Citation
    with SessionLocal() as db:
        doc=create_document_from_pages(db,[ParsedPage(1,'Pakistan interest rates and inflation affect cement financing costs.')],
            title='HTML article',document_type='news',source_url='https://publisher.test/article',physical_pages=False,commit=False)
        assert all(r.page_number is None for r in db.scalars(select(Citation).where(Citation.document_id==doc.id)))
        assert sections(db,doc.id)[0].page_number is None


def test_source_revisions_requeue_without_losing_previous_artifact(monkeypatch):
    from app.ingestion.evidence import Candidate
    from app.services.evidence_pipeline import ensure_source_config,persist_candidate
    from app.models.evidence import DiscoveryCandidate
    monkeypatch.setattr(settings,'pipeline_enabled',True)
    with SessionLocal() as db:
        _,config,_=ensure_source_config(db,'mettis')
        candidate=Candidate(source_key='mettis',observed_url='https://mettisglobal.news/story',headline='Lucky Cement expansion',publisher='Mettis',discovered_at=datetime.now(UTC),discovery_method='fixture',metadata={'summary':'Proposed expansion'})
        row,_=persist_candidate(db,config,candidate);db.flush();row.status='selected';row.fetched_at=datetime.now(UTC)
        updated=__import__('dataclasses').replace(candidate,headline='Lucky Cement cancels expansion')
        revised,changed=persist_candidate(db,config,updated)
        assert changed and revised.id==row.id and revised.status=='fetch_ready'
        assert json.loads(revised.metadata_json)['pipeline_revision']==1


def test_exchange_status_does_not_make_holiday_quotes_fresh():
    from app.services.pipeline.prices import regular_market_state
    assert regular_market_state('<table><tr><td>Regular</td><td>Closed</td></tr></table>')=='closed'
    assert regular_market_state('<table><tr><td>Regular</td><td>Open</td></tr></table>')=='open'
    with pytest.raises(ValueError): regular_market_state('<table><tr><td>Futures</td><td>Open</td></tr></table>')


def test_scstrade_issuer_sessions_are_isolated():
    import httpx
    from app.providers.fundamentals.scstrade_tables import ScsTradeTablesProvider
    seen=[]
    def handler(request):
        if request.method=='GET':
            symbol=request.url.params['symbol'];return httpx.Response(200,text='Company page',headers={'set-cookie':'issuer='+symbol})
        payload=json.loads(request.content)
        assert 'issuer='+payload['sym'] in request.headers.get('cookie','')
        seen.append(payload['sym'])
        assert payload['rows']==100 and payload['sidx']=='Year / Quarter'
        return httpx.Response(200,json={'d':{'rows':[]}})
    provider=ScsTradeTablesProvider(transport=httpx.MockTransport(handler))
    assert len(provider.fetch('LUCK'))==3
    assert len(provider.fetch('FFC'))==3
    assert seen==['LUCK']*3+['FFC']*3


def test_fx_delta_is_exact_quote_change_and_stale_cpi_is_labelled():
    from app.services.ingestion_persistence import source,store_artifact
    from app.models.workstation import MacroSeries,MacroObservation
    from app.services.regime_service import macro_regime
    from app.models.user import User
    with SessionLocal() as db:
        publisher=source(db,'SBP fixture','macro','https://sbp.test',1,60,'fixture')
        artifact=store_artifact(db,publisher,b'offline fixture',url='https://sbp.test/fx',method='GET',parser_version='fixture',content_type='text/plain')
        fx=MacroSeries(key='PK_USD_PKR',name='Pakistan rupees per dollar',unit='PKR_per_USD',frequency='daily',source_id=publisher.id)
        cpi=MacroSeries(key='PK_CPI_YOY',name='Pakistan CPI inflation',unit='percent_yoy',frequency='monthly',source_id=publisher.id)
        db.add_all([fx,cpi]);db.flush()
        for series,day,value in [(fx,date.today()-timedelta(days=1),'277.6522'),(fx,date.today(),'277.0714'),(cpi,date(2025,1,1),'2.4')]:
            db.add(MacroObservation(series_id=series.id,effective_date=day,value=Decimal(value),artifact_id=artifact.id,is_selected=True))
        user=User(email='macro-fixture@test.local',password_hash='unused');db.add(user);db.flush()
        result=macro_regime(db,user)
        currency=result['dimensions']['currency']
        assert Decimal(currency['change'])==Decimal('-.5808')
        assert Decimal(currency['quote_change_percent'])==Decimal('-.5808')/Decimal('277.6522')*100
        assert currency['pkr_direction']=='appreciation'
        assert currency['source_url']=='https://sbp.test/fx'
        assert result['dimensions']['inflation']['freshness_status']=='stale'
