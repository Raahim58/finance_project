"""Offline integration checks for the agreed IPS/allocation/event corrections."""
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db.session import SessionLocal
from app.models.user import User
from app.models.portfolio import Portfolio
from app.models.workstation import PortfolioIPSVersion, Instrument, Event, EventEntityLink, EventSource
from app.tools import build_tool_registry
from app.tools.registry import expand_model_data
from app.ai.tool_loop import _render_allocation
from app.services.workstation_service import ips_compliance
from app.services.research_intelligence_service import company_event_page, company_events


def ips_fixture(db, monkeypatch):
    user = User(email='ips-scope@test.invalid', password_hash='fixture')
    db.add(user); db.flush()
    portfolio = Portfolio(user_id=user.id, name='Fixture', base_currency='PKR')
    db.add(portfolio); db.flush()
    version = PortfolioIPSVersion(portfolio_id=portfolio.id, version=1, status='confirmed',
        confirmed_at=datetime.now(UTC), constraints_json=json.dumps({
            'max_instrument_weight': .5, 'target_volatility': .2, 'risk_budgets': {'LUCK': .1}}))
    db.add(version); db.flush(); portfolio.selected_ips_version_id = version.id; db.flush()
    db.add(Instrument(symbol='LUCK', name='Fixture company', sector='Cement'))
    db.flush()
    summary = SimpleNamespace(total_value=Decimal(1000), cash_balance=Decimal(100), data_freshness_date=date.today(),
        valuation_complete=True, unpriced_symbols=[], holdings=[SimpleNamespace(symbol='LUCK', sector='Cement',
        market_value=Decimal(900), data_source='fixture', latest_price_date=date.today(), artifact_id=None)])
    monkeypatch.setattr('app.services.workstation_service.get_portfolio_summary', lambda *_: summary)
    return user, portfolio, version


@pytest.mark.usefixtures("database")
def test_optional_sql_failure_preserves_cash_weight_checks_and_transaction(monkeypatch):
    with SessionLocal() as db:
        user, portfolio, _ = ips_fixture(db, monkeypatch)
        def fail(db, *_args, **_kwargs):
            db.execute(text('SELECT * FROM unavailable_optional_risk_source'))
        monkeypatch.setattr('app.services.workstation_service.portfolio_quant', fail)
        result = expand_model_data(build_tool_registry().invoke('ips.compliance', db, user, {'portfolio_id': portfolio.id}))
        assert result['status'] == 'ok'
        assert result['data']['modeled_analysis']['status'] == 'unavailable'
        assert result['data']['status'] == 'BREACH'
        assert any(c['code']=='max_instrument_weight' for c in result['data']['violations'])
        assert {c['code'] for c in result['data']['not_evaluated']} >= {'target_volatility', 'risk_budgets'}
        assert db.scalar(text('SELECT 1')) == 1
        assert 'unavailable_optional_risk_source' not in json.dumps(result)


@pytest.mark.usefixtures("database")
def test_disk_full_is_not_retried_and_is_reported_without_private_sql(monkeypatch):
    class DiskFull(Exception):
        sqlstate = '53100'
    calls = []
    with SessionLocal() as db:
        user, portfolio, _ = ips_fixture(db, monkeypatch)
        def fail(*args, **kwargs):
            calls.append(kwargs)
            raise OperationalError('private SQL', {'private': 'values'}, DiskFull('disk full'))
        monkeypatch.setattr('app.services.workstation_service.portfolio_quant', fail)
        result = ips_compliance(db, user, portfolio.id, persist_analysis=False)
        assert calls == [{'persist': False}]
        assert result['modeled_analysis'] == {'status':'unavailable', 'error_type':'DiskFull', 'sqlstate':'53100'}
        assert 'private SQL' not in json.dumps(result, default=str)


@pytest.mark.usefixtures("database")
def test_draft_ips_is_not_evaluated_and_other_owner_is_denied(monkeypatch):
    with SessionLocal() as db:
        user, portfolio, version = ips_fixture(db, monkeypatch)
        version.status='draft'; version.confirmed_at=None; db.flush()
        result = ips_compliance(db, user, portfolio.id, persist_analysis=False)
        assert result['status']=='NOT_EVALUATED' and result['ips_version_id'] is None
        other=User(email='other-scope@test.invalid',password_hash='fixture');db.add(other);db.flush()
        denied=build_tool_registry().invoke('ips.compliance', db, other, {'portfolio_id':portfolio.id})
        assert denied['status']=='missing'


def test_rejected_allocation_has_no_recommended_rows_but_retains_failed_checks():
    text_result, outcome = _render_allocation({'allocation_check': {
        'accepted':False, 'verification_id':'rejected-1', 'errors':['ips_breach'],
        'current_weights':{'LUCK':.2}, 'proposed_weights':{'LUCK':.8},
        'legs':[{'instrument_id':'LUCK','side':'buy','quantity':'10'}],
        'checks':{'ips_compliance':{'status':'BREACH'}}}})
    assert outcome['status']=='rejected' and outcome['verification_id']=='rejected-1'
    assert outcome['rows']==[] and outcome['legs']==[]
    assert outcome['checks']['ips_compliance']['status']=='BREACH'
    assert 'ips_breach' in text_result and '80%' not in text_result
    text_result, outcome = _render_allocation({})
    assert text_result=='' and outcome['status']=='not_requested'


def event_fixture(db, monkeypatch):
    user=User(email='event-scope@test.invalid',password_hash='fixture')
    a=Instrument(symbol='LUCK',name='Fixture cement');b=Instrument(symbol='OGDC',name='Fixture energy')
    db.add_all([user,a,b]);db.flush()
    direct = {'id':'direct-1', 'event_key':'raw:direct-1', 'title':'Fixture LUCK issuer notice',
        'occurred_at':datetime(2026,8,12,tzinfo=UTC), 'materiality':'medium', 'factors':[],
        'subjects':[{'subject_key':'LUCK'}], 'evidence':[{'id':'chunk:direct', 'text':'Fixture issuer evidence',
        'source_name':'Fixture source','source_url':'https://example.test/direct'}]}
    oil = {'id':'oil-1', 'event_key':'raw:oil-1', 'title':'Fixture Brent price news',
        'occurred_at':datetime(2026,8,13,tzinfo=UTC), 'materiality':'high', 'factors':['oil_price'],
        'subjects':[], 'evidence':[{'id':'chunk:oil','text':'Fixture commodity-price evidence',
        'source_name':'Fixture source','source_url':'https://example.test/oil'}]}
    geo = dict(oil,id='geo-1',event_key='raw:geo-1',title='Fixture geopolitical conflict',factors=[])
    def views(_db, **kw):
        if kw.get('symbol')=='LUCK':return [dict(direct)]
        if kw.get('symbol')=='OGDC':return [dict(direct,id='ogdc-direct',event_key='raw:ogdc-direct',subjects=[{'subject_key':'OGDC'}])]
        return [dict(oil),dict(geo)]
    def profile(_db, owner, instrument):
        assert owner.id==user.id
        return SimpleNamespace(relationships_json=json.dumps([{'factor':'oil_price','mechanism':'Fixture energy-cost exposure'}])) if instrument.symbol=='LUCK' else None
    monkeypatch.setattr('app.services.research_intelligence_service.event_views', views)
    monkeypatch.setattr('app.services.research_intelligence_service.current_profile', profile)
    monkeypatch.setattr('app.services.research_service.list_events', lambda *_args, **_kwargs: [])
    return user,a,b


@pytest.mark.usefixtures("database")
def test_matching_before_pagination_is_shared_across_all_three_assistant_tools(monkeypatch):
    with SessionLocal() as db:
        user,a,b=event_fixture(db,monkeypatch)
        first=company_event_page(db,user,a,limit=1)
        assert first['events'][0]['relationship_kind']=='ai_proposed_indirect'
        assert first['coverage']['continuation']=='1'
        second=company_event_page(db,user,a,offset=1,limit=1)
        assert second['events'][0]['relationship_kind']=='direct'
        assert second['coverage']['continuation'] is None
        registry=build_tool_registry()
        for name,args in [('research.events',{'entity_key':'LUCK','limit':1}),
                          ('research.event_relevance',{'symbol':'LUCK','limit':1}),
                          ('research.company_sections',{'instrument_id':a.id,'sections':['events'],'limit':1})]:
            result=expand_model_data(registry.invoke(name,db,user,args))
            assert result['status']=='ok', result
            data=result['data'];rows=data['events'] if 'events' in data else data['sections'][0]['data']
            assert rows[0]['id']=='oil-1'
            assert 'relevance_reason' in rows[0]
            assert rows[0]['evidence_excerpts'][0]['text']=='Fixture commodity-price evidence'
            assert result['sources'][0]['source_url']=='https://example.test/oil'
            assert result['coverage']['continuation']=='1'
        unprofiled=company_event_page(db,user,b)
        assert unprofiled['events'][0]['relationship_kind']=='direct'
        assert unprofiled['coverage']['exposure_profile_available'] is False
        empty=company_event_page(db,user,a,offset=99)
        assert empty['events']==[] and empty['coverage']['matched_in_scan']==2
        assert empty['coverage']['completeness']=='bounded_scan'
        # No reason/coverage additions alter the background digest payload.
        assert all('relevance_reason' not in r for r in company_events(db,user,a))


@pytest.mark.usefixtures("database")
def test_broader_geopolitical_search_has_no_company_or_three_factor_gate(monkeypatch):
    with SessionLocal() as db:
        user=User(email='broad-scope@test.invalid',password_hash='fixture');db.add(user);db.flush()
        for title in ['Fixture geopolitical conflict disrupts shipping','Fixture company earnings']:
            event=Event(event_type='news',title=title,occurred_at=datetime.now(UTC));db.add(event);db.flush()
            db.add(EventSource(event_id=event.id,source_name='Fixture source',source_url='https://example.test/news'))
        db.flush()
        result=expand_model_data(build_tool_registry().invoke('research.events',db,user,{'query':'geopolitical','limit':1}))
        assert result['status']=='ok' and len(result['data']['events'])==1
        assert 'geopolitical' in result['data']['events'][0]['title']
        assert result['data']['search_coverage']['scope']=='broader_stored_events'
        assert result['sources'][0]['source_url']=='https://example.test/news'


@pytest.mark.usefixtures("database")
def test_legacy_direct_sources_survive_case_insensitive_matching_and_paginate_once(monkeypatch):
    with SessionLocal() as db:
        user=User(email='legacy-scope@test.invalid',password_hash='fixture')
        company=Instrument(symbol='LUCK',name='Fixture cement')
        db.add_all([user,company]);db.flush()
        for day in (10,11):
            e=Event(event_type='news',title=f'Fixture issuer notice {day}',occurred_at=datetime(2026,8,day,tzinfo=UTC))
            db.add(e);db.flush()
            db.add(EventEntityLink(event_id=e.id,entity_type='instrument',entity_key='luck',link_method='fixture',confidence=1))
            db.add(EventSource(event_id=e.id,source_name='Fixture source',source_url=f'https://example.test/{day}'))
        db.flush()
        monkeypatch.setattr('app.services.research_intelligence_service.current_profile',lambda *_:None)
        first=company_event_page(db,user,company,start=date(2026,8,10),end=date(2026,8,11),limit=1)
        second=company_event_page(db,user,company,start=date(2026,8,10),end=date(2026,8,11),offset=1,limit=1)
        assert first['coverage']['continuation']=='1' and second['coverage']['continuation'] is None
        assert first['events'][0]['id']!=second['events'][0]['id']
        assert first['events'][0]['relationship_kind']=='direct'
