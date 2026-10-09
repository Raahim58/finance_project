import json
from datetime import date
from decimal import Decimal
import httpx
import pytest
from sqlalchemy import select,func
from app.db.session import SessionLocal
from app.ingestion.artifact_store import LocalArtifactStore
from app.models.workstation import Instrument,MarketObservation,CorporateAction,SourceArtifact
from app.services.index_ingestion import import_index_month
from app.services.market_ingestion import persist_market_data
from app.services.market_providers import LatestPriceRow
from app.services.canonical_market_service import price_series,latest_price
from app.services.split_adjustments import split_adjusted_price_series

HTML='<table id="historicalTable"><tr><th>DATE</th><th>OPEN</th><th>HIGH</th><th>LOW</th><th>CLOSE</th><th>VOLUME</th></tr><tr><td>Sep 01, 2026</td><td>100</td><td>102</td><td>99</td><td>101</td><td>10</td></tr><tr><td>Sep 02, 2026</td><td>101</td><td>104</td><td>100</td><td>103</td><td>20</td></tr></table>'

class Client:
    def __init__(self,text=HTML):self.text=text
    def post(self,path,data):
        assert path=='/historical' and data['year']=='2026'
        return httpx.Response(200,text=self.text,request=httpx.Request('POST','https://dps.psx.com.pk/historical'))


def test_index_month_preserves_basis_raw_artifacts_and_is_idempotent(tmp_path):
    with SessionLocal() as db:
        store=LocalArtifactStore(tmp_path)
        first=import_index_month(db,'KSE100',date(2026,9,1),Client(),store);db.commit()
        second=import_index_month(db,'KSE100',date(2026,9,1),Client(),store)
        other=import_index_month(db,'KSE100PR',date(2026,9,1),Client(),store)
        assert first['written']==2 and second['written']==0
        assert other['return_basis']=='price_return'
        rows=price_series(db,'KSE100');assert [r.close for r in rows]==[Decimal(101),Decimal(103)]
        assert rows[1].previous_close==Decimal(101)
        assert json.loads(db.scalar(select(Instrument).where(Instrument.symbol=='KSE100')).metadata_json)['return_basis']=='total_return'
        assert db.scalar(select(func.count()).select_from(MarketObservation).where(MarketObservation.is_selected.is_(True)))==8
        artifact=db.get(SourceArtifact,first['artifact_id']);assert store.get(artifact.storage_path).decode()==HTML


def test_index_month_rejects_bad_row_and_wrong_month(tmp_path):
    with SessionLocal() as db:
        for text in [HTML.replace('<td>103</td>','<td>bad</td>'),HTML.replace('Sep 02','Aug 02')]:
            with pytest.raises(ValueError):import_index_month(db,'KSE100',date(2026,9,1),Client(text),LocalArtifactStore(tmp_path))
        assert db.scalar(select(func.count()).select_from(MarketObservation))==0


def test_index_month_deduplicates_exact_rows_but_rejects_conflicting_duplicates(tmp_path):
    from bs4 import BeautifulSoup
    row = str(BeautifulSoup(HTML, 'html.parser').find_all('tr')[1])
    with SessionLocal() as db:
        result=import_index_month(db,'KSE100',date(2026,9,1),
            Client(HTML.replace('</table>',row+'</table>')),LocalArtifactStore(tmp_path))
        assert result['rows']==2 and result['written']==2
        conflicting=row.replace('<td>101</td>','<td>100.5</td>')
        with pytest.raises(ValueError,match='Conflicting'):
            import_index_month(db,'KSE100',date(2026,9,1),
                Client(HTML.replace('</table>',conflicting+'</table>')),LocalArtifactStore(tmp_path))


def seed_split(db):
    for day,close in [(date(2026,1,1),'500'),(date(2026,1,2),'102'),(date(2026,1,5),'104')]:
        persist_market_data(db,latest_prices=[LatestPriceRow(symbol='TEST',trade_date=day,close=Decimal(close),previous_close=Decimal(close),open=Decimal(close),high=Decimal(close),low=Decimal(close),volume=10,name='Synthetic split test',sector='Test',source_url='https://example.com/fixture')],source='dps')
    instrument=db.scalar(select(Instrument).where(Instrument.symbol=='TEST'))
    artifact=db.scalar(select(SourceArtifact))
    action=CorporateAction(instrument_id=instrument.id,action_type='stock_split',effective_date=date(2026,1,2),artifact_id=artifact.id,details_json=json.dumps({'old_shares':'1','new_shares':'5','verification':'source_reviewed'}))
    db.add(action);db.flush();return action


def test_split_view_removes_mechanical_jump_without_mutating_raw_prices():
    with SessionLocal() as db:
        action=seed_split(db)
        raw=price_series(db,'TEST');adjusted=split_adjusted_price_series(db,'TEST')
        assert [r.close for r in adjusted]==[Decimal(100),Decimal(102),Decimal(104)]
        assert adjusted[1].previous_close==Decimal(100)
        assert adjusted[1].close/adjusted[0].close-1==Decimal('.02')
        assert price_series(db,'TEST')==raw and latest_price(db,'TEST').close==Decimal(104)
        assert split_adjusted_price_series(db,'TEST',end=date(2026,1,1))[0].close==Decimal(500)
        action.details_json=json.dumps({'old_shares':'1','new_shares':'5','verification':'unverified'})
        assert split_adjusted_price_series(db,'TEST')==raw


def test_split_ratios_compound_and_invalid_ratios_fail():
    with SessionLocal() as db:
        action=seed_split(db)
        db.add(CorporateAction(instrument_id=action.instrument_id,action_type='stock_split',effective_date=date(2026,1,5),artifact_id=action.artifact_id,details_json=json.dumps({'old_shares':'1','new_shares':'2','verification':'source_reviewed'})));db.flush()
        assert split_adjusted_price_series(db,'TEST')[0].close==Decimal(50)
        action.details_json=json.dumps({'old_shares':'0','new_shares':'5','verification':'source_reviewed'})
        with pytest.raises(ValueError):split_adjusted_price_series(db,'TEST')


def test_recorded_split_requires_matching_source_quote_and_is_idempotent():
    from app.models.document import Document,DocumentPage
    from app.jobs.record_sourced_split import record_split
    with SessionLocal() as db:
        action=seed_split(db);db.delete(action);db.flush()
        quote='A 5-for-1 share split was successfully executed on January 2, 2026, improving liquidity.'
        doc=Document(symbol='TEST',document_type='annual_report',title='Synthetic test report',source_name='test fixture',source_url='https://example.com/fixture',content_hash='fixture',artifact_id=action.artifact_id)
        db.add(doc);db.flush();db.add(DocumentPage(document_id=doc.id,page_number=1,text=quote));db.flush()
        with pytest.raises(ValueError,match='quote'):
            record_split(db,doc.id,1,'TEST',date(2026,1,2),1,5,'Not present in this retained report page at all.')
        with pytest.raises(ValueError,match='ratio'):
            record_split(db,doc.id,1,'TEST',date(2026,1,2),1,4,quote)
        first=record_split(db,doc.id,1,'TEST',date(2026,1,2),1,5,quote)
        second=record_split(db,doc.id,1,'TEST',date(2026,1,2),1,5,quote)
        assert first.id==second.id and json.loads(first.details_json)['split_multiplier']=='5'


def test_invalid_ohlc_does_not_destroy_a_valid_index_close(tmp_path):
    from app.services.canonical_market_service import close_series
    from app.models.workstation import DataQualityIssue
    with SessionLocal() as db:
        result=import_index_month(db,'KSE100',date(2026,9,1),Client(HTML.replace('<td>104</td>','<td>102</td>')),LocalArtifactStore(tmp_path))
        assert result['rows']==2 and result['ohlc_rows']==1 and result['rejected_ohlc_rows']==1
        assert close_series(db,'KSE100')[date(2026,9,2)]==Decimal(103)
        assert len(price_series(db,'KSE100'))==1
        assert db.scalar(select(DataQualityIssue.rule))=='index_ohlc_rejected_close_retained'


def test_market_overview_uses_index_closes_and_excludes_index_volume(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.services import market_service
    with SessionLocal() as db:
        import_index_month(db,'KSE100',date(2026,9,1),Client(HTML),LocalArtifactStore(tmp_path))
        db.add(Instrument(symbol='AAA',name='Observed fixture',instrument_type='equity'))
        db.add(Instrument(symbol='KSE100PR',name='Index fixture',instrument_type='index'))
        db.flush()
        rows=[SimpleNamespace(symbol='AAA',volume=7,value=Decimal(70)),
              SimpleNamespace(symbol='KSE100',volume=9000,value=Decimal(90000)),
              SimpleNamespace(symbol='KSE100PR',volume=9000,value=Decimal(90000))]
        monkeypatch.setattr(market_service,'canonical_prices_for_date',lambda *_:rows)
        snapshot=market_service.get_market_snapshot(db,date(2026,9,2))
        assert snapshot.index_value==Decimal(103)
        assert snapshot.index_change==Decimal(2)
        assert snapshot.total_volume==7 and snapshot.total_value==Decimal(70)
        assert '1 stored securities' in snapshot.totals_note
        assert snapshot.source_url.startswith('https://dps.psx.com.pk/historical')
        assert [r.symbol for r in market_service._prices_for_date(db,date(2026,9,2))]==['AAA']
