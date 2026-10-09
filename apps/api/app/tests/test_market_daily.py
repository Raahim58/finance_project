import json
from datetime import date, datetime, UTC
from decimal import Decimal

import httpx
import pandas as pd
import pytest
from sqlalchemy import select, func

from app.db.session import SessionLocal
from app.models.workstation import Instrument, CorporateAction, MarketObservation, IngestionRun
from app.services.dps_capitalization import HEADERS, parse_constituents, import_capitalization, capitalization
from app.services.corporate_action_ingestion import HEADERS as PAYOUT_HEADERS, parse_payouts, import_payout_page
from app.services.market_providers import DpsMarketDataProvider
from app.jobs.market_daily import target_day, recent_weekdays, run_stage


def workbook(monkeypatch, bad=False):
    ordinary = ['PKTEST', 'TEST', 'Synthetic test', '10', '1', '20', '200', '100', '1000', '1']
    if bad: ordinary[8] = '900'
    index = ordinary.copy(); index[7] = '20'; index[8] = '200'
    monkeypatch.setattr(pd, 'read_excel', lambda *a, **k: {
        'KSE-ALL-Shares': pd.DataFrame([ordinary], columns=HEADERS),
        'KSE-100': pd.DataFrame([index], columns=HEADERS)})


def payouts(text='10% (D) 20% (B)'):
    return '<table id="announcementsTable"><tr>' + ''.join('<th>'+h+'</th>' for h in PAYOUT_HEADERS) + '</tr><tr>' + ''.join(
        '<td>'+v+'</td>' for v in ['TEST','Synthetic test','Test',text,'October 01, 2026 4:07 PM','21/10/2026 - 28/10/2026']) + '</tr></table>Showing 1 to 1 of 1 entries'


class Client:
    def get(self, url): return httpx.Response(200, content=b'synthetic workbook', request=httpx.Request('GET',url))
    def post(self, url, data): return httpx.Response(200, text=payouts(), request=httpx.Request('POST','https://dps.psx.com.pk'+url))


def test_total_shares_use_all_shares_not_index_float(monkeypatch):
    workbook(monkeypatch)
    rows, issues = parse_constituents(b'fixture')
    assert not issues
    assert rows['TEST']['ordinary_shares'] == '100'
    assert rows['TEST']['free_float_shares'] == '20'
    assert rows['TEST']['index_weights_percent']['KSE-100'] == '1'
    workbook(monkeypatch, bad=True)
    with pytest.raises(ValueError, match='no validated'): parse_constituents(b'fixture')


@pytest.mark.usefixtures("database")
def test_capitalization_idempotency_and_no_future_leak(monkeypatch, tmp_path):
    from app.ingestion.artifact_store import LocalArtifactStore
    monkeypatch.setattr('app.services.ingestion_persistence.get_artifact_store', lambda *_: LocalArtifactStore(tmp_path))
    workbook(monkeypatch)
    with SessionLocal() as db:
        instrument = Instrument(symbol='TEST', name='Synthetic test'); db.add(instrument); db.commit()
        first = import_capitalization(db,Client(),date(2026,10,2)); db.commit()
        second = import_capitalization(db,Client(),date(2026,10,2)); db.commit()
        assert first['written'] == 1 and second['written'] == 0
        assert capitalization(db,instrument.id,date(2026,10,1)) is None
        assert capitalization(db,instrument.id,date(2026,10,2))['market_cap'] == '1000'
        assert db.scalar(select(func.count()).select_from(MarketObservation)) == 1


@pytest.mark.usefixtures("database")
def test_announcements_do_not_invent_dividend_amount_or_ex_date(monkeypatch, tmp_path):
    from app.ingestion.artifact_store import LocalArtifactStore
    monkeypatch.setattr('app.services.ingestion_persistence.get_artifact_store', lambda *_: LocalArtifactStore(tmp_path))
    rows, total, issues = parse_payouts(payouts())
    assert total == 1 and not issues and len(rows) == 2
    with SessionLocal() as db:
        db.add(Instrument(symbol='TEST',name='Synthetic test'));db.commit()
        assert import_payout_page(db,Client())['written'] == 2;db.commit()
        assert import_payout_page(db,Client())['written'] == 0;db.commit()
        for action in db.scalars(select(CorporateAction)):
            assert action.ex_date is None and action.payment_date is None
            assert json.loads(action.details_json)['cash_per_share'] is None
            assert action.action_type.endswith('_announced')
    with pytest.raises(ValueError): parse_payouts('<html>error</html>')


def test_eod_target_and_recent_weekdays():
    assert target_day(datetime(2026,10,5,12,0,tzinfo=UTC)) == date(2026,10,2)
    assert target_day(datetime(2026,10,5,14,0,tzinfo=UTC)) == date(2026,10,5)
    assert recent_weekdays(date(2026,10,5)) == [date(2026,10,d) for d in [5,2,1]] + [date(2026,9,d) for d in [30,29]]


@pytest.mark.usefixtures("database")
def test_durable_stages_skip_success_and_throttle_failures():
    calls=[]
    def operation(db): calls.append(1); return {'accepted':3, 'coverage_status':'partial'}
    assert run_stage('prices',date(2026,10,2),operation)['status'] == 'completed'
    assert run_stage('prices',date(2026,10,2),operation)['status'] == 'already_completed'
    assert len(calls) == 1
    def failure(db): raise RuntimeError('Synthetic source failure')
    assert run_stage('capitalization',date(2026,10,2),failure)['status'] == 'failed'
    assert run_stage('capitalization',date(2026,10,2),operation)['status'] == 'retry_wait'
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(IngestionRun)) == 2


def test_company_history_exact_duplicates_and_conflicts():
    headers='<tr>'+''.join('<th>'+h+'</th>' for h in ['DATE','OPEN','HIGH','LOW','CLOSE','VOLUME'])+'</tr>'
    row='<tr>'+''.join('<td>'+v+'</td>' for v in ['Oct 02, 2026','10','12','9','11','100'])+'</tr>'
    assert len(DpsMarketDataProvider.parse_symbol_history('<table id="historicalTable">'+headers+row+row+'</table>','TEST')) == 1
    with pytest.raises(ValueError,match='Conflicting'):
        DpsMarketDataProvider.parse_symbol_history('<table id="historicalTable">'+headers+row+row.replace('<td>11</td>','<td>10</td>')+'</table>','TEST')


@pytest.mark.usefixtures("database")
def test_reviewed_bonus_validates_date_ratio_and_is_idempotent(monkeypatch, tmp_path):
    from hashlib import sha256
    from types import SimpleNamespace
    from app.jobs.reviewed_corporate_actions import import_reviewed_action
    from app.ingestion.artifact_store import LocalArtifactStore
    content = b'Synthetic pinned PDF'; quote = 'Synthetic issuer declared 800% (B); ex date 16-Sep-2024.'
    monkeypatch.setattr('app.jobs.reviewed_corporate_actions.PdfReader', lambda *_: SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda:quote)]))
    monkeypatch.setattr('app.services.ingestion_persistence.get_artifact_store', lambda *_: LocalArtifactStore(tmp_path))
    class PDFClient:
        def get(self,url): return httpx.Response(200,content=content,request=httpx.Request('GET',url))
    item = {'symbol':'TEST','action_type':'bonus_issue','ex_date':'2024-09-16', 'date_evidence':'16-Sep-2024',
        'old_shares':'1','new_shares':'9','ratio_evidence':'800% (B)',
        'evidence':[{'url':'https://dps.psx.com.pk/download/document/fixture.pdf','page':1,'quote':quote,'sha256':sha256(content).hexdigest()}]}
    with SessionLocal() as db:
        db.add(Instrument(symbol='TEST',name='Synthetic test'));db.commit()
        action=import_reviewed_action(db,PDFClient(),item);db.commit()
        assert action.id==import_reviewed_action(db,PDFClient(),item).id
        with pytest.raises(ValueError,match='multiplier'):import_reviewed_action(db,PDFClient(),{**item,'new_shares':'8'})
        with pytest.raises(ValueError,match='Ex date'):import_reviewed_action(db,PDFClient(),{**item,'ex_date':'2024-09-17'})
        assert db.scalar(select(func.count()).select_from(CorporateAction))==1


@pytest.mark.usefixtures("database")
def test_same_date_capitalization_enriches_price_but_never_future(monkeypatch, tmp_path):
    from app.ingestion.artifact_store import LocalArtifactStore
    from app.services.market_ingestion import persist_market_data
    from app.services.market_providers import LatestPriceRow
    from app.services.canonical_market_service import latest_price
    monkeypatch.setattr('app.services.ingestion_persistence.get_artifact_store', lambda *_: LocalArtifactStore(tmp_path))
    workbook(monkeypatch)
    with SessionLocal() as db:
        persist_market_data(db,latest_prices=[LatestPriceRow(symbol='TEST',trade_date=date(2026,10,1),
            close=Decimal(10),previous_close=Decimal(10),open=Decimal(10),high=Decimal(10),low=Decimal(10),volume=1,
            name='Synthetic test',sector='Test',source_url='https://example.com/fixture')],source='dps')
        db.commit()
        import_capitalization(db,Client(),date(2026,10,2));db.commit()
        assert latest_price(db,'TEST').market_cap is None
        persist_market_data(db,latest_prices=[LatestPriceRow(symbol='TEST',trade_date=date(2026,10,2),
            close=Decimal(10),previous_close=Decimal(10),open=Decimal(10),high=Decimal(10),low=Decimal(10),volume=1,
            name='Synthetic test',sector='Test',source_url='https://example.com/fixture')],source='dps');db.commit()
        assert latest_price(db,'TEST').market_cap == Decimal(1000)
        from app.services.canonical_market_service import canonical_prices_for_date
        assert canonical_prices_for_date(db,date(2026,10,2))[0].market_cap == Decimal(1000)
        assert canonical_prices_for_date(db,date(2026,10,1))[0].market_cap is None


@pytest.mark.usefixtures("database")
def test_verified_bonus_is_adjusted_but_announcement_is_not():
    from app.tests.support.market import seed_split
    from app.services.split_adjustments import split_adjusted_price_series
    with SessionLocal() as db:
        # Existing split fixture establishes sourced observations and artifacts.
        action = seed_split(db)
        action.action_type = 'bonus_issue';db.commit()
        adjusted=split_adjusted_price_series(db,'TEST')
        assert adjusted[0].adjustment_state == 'sourced_split_adjusted'
        action.action_type = 'bonus_issue_announced';db.commit()
        assert split_adjusted_price_series(db,'TEST')[0].adjustment_state == 'unadjusted'


@pytest.mark.parametrize('label', ['25%(ii) (D)', '25%( iii) (D)', '25% (IV) (D)', 'DIVIDEND =25%(F)'])
def test_official_payout_notation_variants(label):
    records,total,issues=parse_payouts(payouts(label))
    assert not issues and records[0]['kind']=='D' and records[0]['payout_percent']=='25'


@pytest.mark.usefixtures("database")
def test_adjusted_previous_close_handles_action_on_nontrading_date():
    from app.tests.support.market import seed_split
    from app.services.split_adjustments import split_adjusted_price_series
    with SessionLocal() as db:
        action = seed_split(db)
        action.effective_date = date(2026,1,4)
        db.commit()
        adjusted = split_adjusted_price_series(db,'TEST')
        assert adjusted[-1].previous_close == adjusted[-2].close == Decimal('20.4')
