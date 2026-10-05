"""Persistent digest, compact facts and queue invariants; no external calls."""
import asyncio
import json
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.models.user import User
from app.models.workstation import Instrument, FinancialFact
from app.models.llm_key import LLMApiKey
from app.models.research_intelligence import ResearchJob, ResearchAttempt
from app.core.security import encrypt_secret
from app.services.company_snapshot import select_periods, excerpt, build_snapshot, dependency_hash
from app.services.company_digest_service import read_digest, store_snapshot
from app.services.research_generation_service import generation_request, validate_output, brief_projection
from app.tools.registry import expand_model_data
from app.jobs import research_worker
from app.ai.providers.base import LLMProviderResult


def seed(db):
    user=User(email='digest@example.test',password_hash='fixture')
    other=User(email='digest-other@example.test',password_hash='fixture')
    company=Instrument(symbol='AAA',name='Fixture Cement',sector='Cement')
    db.add_all([user,other,company]);db.flush()
    db.add(LLMApiKey(user_id=user.id,provider='zai',default_model='glm-4.5-flash',encrypted_api_key=encrypt_secret('offline-key'),masked_api_key='****'))
    for year in (2022,2023,2024,2025):
        for basis in (True,False):
            for metric,value in (('revenue',100+year-2022),('net_profit',20+year-2022),('eps',3+year-2022)):
                db.add(FinancialFact(instrument_id=company.id,taxonomy_key=metric,period_type='annual',
                    period_start=date(year,1,1),period_end=date(year,12,31),unit='PKR million' if metric!='eps' else 'PKR/share',
                    currency='PKR',consolidated=basis,value=Decimal(value),source_label='Fixture audited report'))
    db.commit();return user,other,company


def stub_sections(monkeypatch):
    from app.tools import research_tools, market_tools
    monkeypatch.setattr(research_tools,'_company_sections',lambda db,u,p:{'status':'missing','data':{'sections':[{'name':str(p.sections[0]),'state':'missing','data':None}]},'sources':[]})
    monkeypatch.setattr(market_tools,'_latest',lambda *args:{'status':'missing','data':{},'sources':[]})
    monkeypatch.setattr(research_tools,'_search',lambda *args,**kwargs:{'status':'ok','data':{'chunks':[{'id':'news-1','group':'company','text':'Management expects expansion to improve margins. However, completion depends on financing.','source_ref':'cite-1','published_date':'2026-10-01','evidence_kind':'commentary'}],'coverage':{'returned':1}},'sources':[{'id':'cite-1','title':'Fixture development','source_name':'Fixture publisher','source_url':'https://example.test/fixture'}]})


def test_selection_and_lossless_projection(monkeypatch):
    stub_sections(monkeypatch)
    with SessionLocal() as db:
        user,_,company=seed(db);snapshot=build_snapshot(db,user,company)
        assert {f['period_end'] for f in snapshot['financials']}=={'2024-12-31','2025-12-31'}
        assert len(snapshot['financials'])==12
        assert {f['accounting_basis'] for f in snapshot['financials']}=={'standalone','consolidated'}
        assert len(snapshot['changes'])==6
        assert all(set(f['evidence_refs'])<=snapshot['sources'].keys() for f in snapshot['financials'])
        projected=brief_projection(snapshot)
        assert expand_model_data(projected['financials'])==snapshot['financials']
        assert expand_model_data(projected['changes'])==snapshot['changes']
        assert snapshot['size']['estimated_tokens']<5000
        assert len(json.dumps(projected))<len(json.dumps(snapshot))
        assert not any(k in snapshot for k in ('portfolio','ips','holdings'))
        print('DIGEST_SIZE='+json.dumps(snapshot['size']))


def test_interim_matches_prior_year_not_previous_quarter():
    rows=[{'id':str(i),'accounting_basis':'consolidated','period_type':'interim','period_start':s,'period_end':e}
          for i,(s,e) in enumerate([('2025-01-01','2025-09-30'),('2024-01-01','2024-09-30'),('2025-01-01','2025-06-30'),('2023-01-01','2023-09-30')])]
    assert [r['id'] for r in select_periods(rows)]==['0','1']


def test_excerpt_retains_adjacent_qualification():
    first=' '.join(['evidence']*105)+'.'
    selected,omitted=excerpt(first+' However, the plan has not received approval. Additional context. Unrelated final sentence.')
    assert 'However, the plan has not received approval.' in selected and omitted


def test_reopen_deduplicates_and_owner_isolation():
    with SessionLocal() as db:
        user,other,company=seed(db)
        first=read_digest(db,user,company,active=True);second=read_digest(db,user,company,active=True)
        assert first['job_id']==second['job_id']
        assert db.scalar(select(func.count()).select_from(ResearchJob))==2
        assert read_digest(db,other,company,active=False)['snapshot'] is None
        assert read_digest(db,other,company,active=False)['job_id'] is None
        assert db.scalar(select(func.count()).select_from(ResearchAttempt))==0


def test_correction_marks_dirty_and_failure_preserves_old_brief(monkeypatch):
    stub_sections(monkeypatch)
    with SessionLocal() as db:
        user,_,company=seed(db);snapshot=build_snapshot(db,user,company);snapshot['input_hash']=dependency_hash(db,company)
        row=store_snapshot(db,user,company,snapshot,{'provider':'zai','model':'glm-4.5-flash'})
        row.brief_json=json.dumps({'thesis':[]});db.commit()
        assert read_digest(db,user,company,active=True)['current']
        assert db.scalar(select(func.count()).select_from(ResearchJob))==0
        fact=db.scalar(select(FinancialFact).where(FinancialFact.period_end==date(2025,12,31)));fact.unit='PKR';db.commit()
        changed=read_digest(db,user,company,active=True)
        assert not changed['current'] and changed['brief']=={'thesis':[]}
        job=db.get(ResearchJob,changed['job_id']);job.status='failed';job.error_code='invalid_model_output';db.commit()
        assert read_digest(db,user,company,active=True)['job_id']==job.id
        retry=read_digest(db,user,company,active=True,retry=True)
        assert retry['job_id']!=job.id and retry['brief']=={'thesis':[]}


def test_unknown_citation_rejected_and_brief_is_separate(monkeypatch):
    stub_sections(monkeypatch)
    with SessionLocal() as db:
        user,_,company=seed(db);snapshot=build_snapshot(db,user,company)
        output={k:[] for k in ('thesis','earnings_drivers','valuation','catalysts','risks','unresolved_questions')}
        output['thesis']=[{'text':'Expansion is conditional.','kind':'interpretation','refs':['news-1']}]
        assert validate_output('company_brief',json.dumps(output),snapshot)==output
        output['thesis'][0]['refs']=['invented']
        with pytest.raises(ValueError,match='unknown_claim_reference'):validate_output('company_brief',json.dumps(output),snapshot)
        messages,_=generation_request('company_brief',snapshot)
        assert 'covariance' not in messages[1]['content'] and len(messages)==2


def test_worker_one_call_saved_and_reopening_zero_calls(monkeypatch):
    stub_sections(monkeypatch);calls=[]
    class Provider:
        async def chat_with_options(self,key,messages,model,*,options):
            calls.append(messages)
            payload=json.loads(messages[1]['content'].split('INPUT_JSON\n')[1].split('\nOUTPUT_SCHEMA')[0])
            output={k:[] for k in ('thesis','earnings_drivers','valuation','catalysts','risks','unresolved_questions')}
            output['thesis']=[{'text':'Expansion remains conditional on financing.','kind':'interpretation','refs':[payload['news'][0]['id']]}]
            return LLMProviderResult(content=json.dumps(output),provider='zai',model=model,input_tokens=2000,output_tokens=200,finish_reason='stop')
    monkeypatch.setattr(research_worker,'get_provider',lambda name:Provider())
    with SessionLocal() as db:
        user,_,company=seed(db);uid,cid=user.id,company.id
        first=read_digest(db,user,company,active=True)
        child=db.scalar(select(ResearchJob).where(ResearchJob.parent_id==first['job_id']))
        child.status='running';db.commit();identifier=child.id
    asyncio.run(research_worker.execute_company(identifier))
    with SessionLocal() as db:
        saved=read_digest(db,db.get(User,uid),db.get(Instrument,cid),active=True)
        assert saved['current'] and saved['status']=='ready', saved
        assert saved['brief']['thesis'][0]['refs']==['news-1'] and len(calls)==1
        assert db.scalar(select(func.count()).select_from(ResearchAttempt))==1
        assert db.get(ResearchJob,first['job_id']).reserved_calls==1
        assert db.get(ResearchJob,first['job_id']).status=='completed'


def test_real_handlers_build_snapshot_without_network():
    with SessionLocal() as db:
        user,_,company=seed(db)
        snapshot=build_snapshot(db,user,company)
        assert len(snapshot['financials'])==12
        assert snapshot['market'].get('close') is None
        assert snapshot['coverage']['live_web_search']=='not_configured'
        assert snapshot['size']['estimated_tokens']<5000


def test_conflicting_values_are_retained_not_averaged(monkeypatch):
    stub_sections(monkeypatch)
    with SessionLocal() as db:
        user,_,company=seed(db)
        db.add(FinancialFact(instrument_id=company.id,taxonomy_key='revenue',period_type='annual',period_start=date(2025,1,1),
            period_end=date(2025,12,31),unit='PKR million',currency='PKR',consolidated=True,value=999,source_label='Contradicting fixture'))
        db.commit();snapshot=build_snapshot(db,user,company)
        assert snapshot['conflicts']
        assert not any(change['basis'][0]=='revenue' and change['basis'][-1]=='consolidated' for change in snapshot['changes'])
        assert len([f for f in snapshot['financials'] if f['metric']=='revenue' and f['accounting_basis']=='consolidated' and f['period_end']=='2025-12-31'])==2


def test_digest_tool_resolves_sources_into_execution_citations(monkeypatch):
    stub_sections(monkeypatch)
    from app.tools.research_tools import _company_digest, CompanyDigestInput
    from app.ai.tool_loop import _attach_evidence
    from app.ai.company_packet import new_packet,merge_result,model_packet
    from app.ai.providers.base import ContentBlock
    with SessionLocal() as db:
        user,_,company=seed(db);snapshot=build_snapshot(db,user,company);snapshot['input_hash']=dependency_hash(db,company)
        row=store_snapshot(db,user,company,snapshot,{'provider':'zai','model':'glm-4.5-flash'})
        row.brief_json=json.dumps({'thesis':[{'text':'Conditional expansion','kind':'interpretation','refs':['S1']}]});db.commit()
        envelope=_company_digest(db,user,CompanyDigestInput(instrument_id=company.id))
        checkpoint={'evidence':{},'next_evidence':1}
        attached=_attach_evidence(checkpoint,envelope)
        packet=new_packet({});merge_result(packet,ContentBlock('tool_call',id='digest',name='research.company_digest',arguments={'instrument_id':company.id}),attached)
        outgoing=model_packet(packet)
        data=expand_model_data(outgoing)['financials'][0]['data']
        assert data['brief']['thesis'][0]['refs'][0].startswith('E')
        assert data['financials'][0]['evidence_refs'][0] in checkpoint['evidence']


def test_new_digest_initial_plan_preserves_followup_budget():
    from app.ai.company_packet import initial_calls
    identity={'explicit_instrument':{'instrument_id':'luck','symbol':'LUCK'}}
    calls=initial_calls(identity,'Review LUCK financials',True,12,use_digests=True)
    assert [c.name for c in calls]==['research.company_digest','market.latest']


def test_late_negative_qualification_is_not_dropped():
    body=' '.join(['Detail about historical operations.']*35)
    selected,omitted=excerpt(body+' However, management cancelled the expansion. Financing remains unavailable.')
    assert 'management cancelled the expansion' in selected and 'Financing remains unavailable.' in selected


def test_over_target_preserves_selected_records(monkeypatch):
    stub_sections(monkeypatch)
    with SessionLocal() as db:
        user,_,company=seed(db)
        for i in range(80):
            db.add(FinancialFact(instrument_id=company.id,taxonomy_key='fixture_metric_'+str(i),period_type='annual',
                period_start=date(2025,1,1),period_end=date(2025,12,31),unit='PKR million',currency='PKR',consolidated=True,
                value=Decimal(i),source_label='Fixture report'))
        db.commit();snapshot=build_snapshot(db,user,company)
        assert len(snapshot['financials'])==92
        assert snapshot['size']['over_target']


def test_provider_failure_saves_snapshot_and_does_not_auto_retry(monkeypatch):
    stub_sections(monkeypatch);calls=[]
    class Provider:
        async def chat_with_options(self,*args,**kwargs):
            calls.append(1);raise TimeoutError('fixture')
    monkeypatch.setattr(research_worker,'get_provider',lambda name:Provider())
    with SessionLocal() as db:
        user,_,company=seed(db);uid,cid=user.id,company.id
        first=read_digest(db,user,company,active=True)
        child=db.scalar(select(ResearchJob).where(ResearchJob.parent_id==first['job_id']));child.status='running';db.commit();jid=child.id
    asyncio.run(research_worker.execute_company(jid))
    with SessionLocal() as db:
        saved=read_digest(db,db.get(User,uid),db.get(Instrument,cid),active=True)
        assert saved['snapshot'] is not None and saved['brief'] is None
        assert saved['status']=='failed' and saved['error_code']=='provider_outcome_unknown'
        assert db.get(ResearchJob,jid).status=='uncertain'
        assert saved['job_id']==first['job_id'] and len(calls)==1


def test_digest_api_requires_auth_and_read_poll_does_not_enqueue(client):
    with SessionLocal() as db:
        user,_,company=seed(db)
        from app.core.security import create_access_token
        token=create_access_token(user.id)
    assert client.get('/research/companies/AAA/digest').status_code==401
    response=client.get('/research/companies/AAA/digest?active=false',headers={'Authorization':'Bearer '+token})
    assert response.status_code==200 and response.json()['job_id'] is None
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ResearchJob))==0


def test_queue_identifiers_fit_postgres_column_limits():
    with SessionLocal() as db:
        user,_,company=seed(db);read_digest(db,user,company,active=True)
        for job in db.scalars(select(ResearchJob)):
            assert len(job.request_hash)==64
            assert len(job.dedup_key)<=160


def test_migration_upgrade_and_downgrade_match_model():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[2]/'alembic/versions/0033_company_digests.py'
    spec=importlib.util.spec_from_file_location('digest_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine('sqlite+pysqlite:///:memory:')
    with engine.begin() as connection:
        migration.op=Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert set(inspect(connection).get_columns('company_digests')[i]['name'] for i in range(10))=={'id','user_id','instrument_id','input_hash','generated_at','prompt_version','provider','model','snapshot_json','brief_json'}
        assert inspect(connection).get_unique_constraints('company_digests')[0]['name']=='uq_company_digest'
        migration.downgrade()
        assert 'company_digests' not in inspect(connection).get_table_names()
