from datetime import date, datetime, UTC
from types import SimpleNamespace
import pytest
from app.jobs.price_history_recovery import months_between, priority_order, covered_month


def test_months_cross_year_and_reject_reversed_window():
    assert list(months_between(date(2025,12,15), date(2026,2,8))) == [date(2025,12,1), date(2026,1,1), date(2026,2,1)]
    with pytest.raises(ValueError):
        list(months_between(date(2026,1,1), date(2025,1,1)))


def test_priority_uses_observed_members_and_holdings_without_guessing_names():
    assert priority_order(['REST','INDEX','HELD','INDEX'], ['HELD'], ['INDEX']) == ['HELD','INDEX','REST']


def test_terminal_month_requires_matching_rows_and_closed_month_capture():
    state=SimpleNamespace(status='complete',item_count=20,completed_at=datetime(2026,9,30,tzinfo=UTC))
    assert covered_month(state,20,date(2026,9,1),date(2026,10,8))
    assert not covered_month(state,0,date(2026,9,1),date(2026,10,8))
    state.completed_at=datetime(2026,9,10,tzinfo=UTC)
    assert not covered_month(state,20,date(2026,9,1),date(2026,10,8))


def test_partial_month_resumes_until_the_requested_asof_is_observed():
    state=SimpleNamespace(status='partial',item_count=6,completed_at=datetime(2026,10,9,tzinfo=UTC))
    assert covered_month(state,6,date(2026,10,1),date(2026,10,8),date(2026,10,8))
    assert not covered_month(state,6,date(2026,10,1),date(2026,10,8),date(2026,10,7))
    assert not covered_month(state,6,date(2026,10,1),date(2026,11,1),date(2026,10,8))


def test_catalog_first_seen_is_not_an_ipo_date():
    from app.services.instrument_history import history_start
    instrument=SimpleNamespace(active_from=date(2026,8,15),metadata_json='{"identity_source":"dps"}')
    assert history_start(instrument,date(2021,10,1)) == date(2021,10,1)
    instrument.metadata_json='{"listing_date_verified":true,"listing_date_source_url":"https://example.test/listing"}'
    assert history_start(instrument,date(2021,10,1)) == date(2026,8,15)
    instrument.metadata_json='{"listing_date_verified":true}'
    assert history_start(instrument,date(2021,10,1)) == date(2021,10,1)


@pytest.mark.usefixtures("database")
def test_enqueue_is_idempotent_and_public_payload_contains_no_portfolio_context():
    from app.db.session import SessionLocal
    from app.jobs.price_history_recovery import queue_batch
    from app.models.pipeline import IngestionStageRun
    from sqlalchemy import select
    rows=[{'symbol':'TEST','instrument_id':'public-instrument','months':[date(2026,9,1)]}]
    with SessionLocal() as db:
        first=queue_batch(db,rows,end=date(2026,10,8))
        second=queue_batch(db,rows,end=date(2026,10,8))
        assert first['created']==1 and second['already_pending']==1
        run=db.scalar(select(IngestionStageRun))
        assert run.input=={'symbol':'TEST','year':2026,'month':9}


@pytest.mark.usefixtures("database")
def test_finished_source_gap_does_not_trap_all_later_batches():
    from app.db.session import SessionLocal
    from app.jobs.price_history_recovery import queue_batch,choose_batch
    from app.models.pipeline import IngestionStageRun
    from sqlalchemy import select
    month=date(2026,9,1)
    first={'symbol':'BLOCKED','instrument_id':'one','months':[month],'as_of':date(2026,10,8)}
    next_row={'symbol':'NEXT','instrument_id':'two','months':[month],'as_of':date(2026,10,8)}
    with SessionLocal() as db:
        queue_batch(db,[first],end=date(2026,10,8))
        run=db.scalar(select(IngestionStageRun));run.status='dead_letter';db.commit()
        batch,pending,gaps=choose_batch(db,[first,next_row],1)
        assert [row['symbol'] for row in batch]==['NEXT']
        assert pending==0 and gaps==1


@pytest.mark.usefixtures("database")
def test_historical_price_dispatch_precedes_other_historical_processing():
    from app.db.session import SessionLocal
    from app.services.pipeline.runs import enqueue,dispatch
    with SessionLocal() as db:
        news=enqueue(db,'classify','document:news',{'document_id':'news'},mode='historical')
        price=enqueue(db,'history_prices','history_price:security:2021-10-01',{'symbol':'TEST','year':2021,'month':10},mode='historical')
        db.commit();published=[]
        assert dispatch(db,lambda identifier,stage,mode:published.append((identifier,stage)),limit=1)==1
        assert published==[(price.id,'history_prices')]


@pytest.mark.usefixtures("database")
def test_price_only_share_does_not_dispatch_document_or_live_market_work():
    from app.db.session import SessionLocal
    from app.services.pipeline.runs import enqueue,dispatch
    with SessionLocal() as db:
        enqueue(db,'classify','document:news',{'document_id':'news'},mode='historical')
        enqueue(db,'prices','target:live',{'symbols':['TEST']})
        price=enqueue(db,'history_prices','history_price:security:2021-10-01',{'symbol':'TEST','year':2021,'month':10},mode='historical')
        db.commit();published=[]
        assert dispatch(db,lambda identifier,stage,mode:published.append((identifier,stage)),limit=4,scope='history_price')==1
        assert published==[(price.id,'history_prices')]
