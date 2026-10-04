"""Official DPS monthly index observations; reuse public-session and artifact contracts."""
import json
from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.ingestion.artifact_store import get_artifact_store
from app.models.workstation import Instrument, MarketObservation, SourceArtifact, DataQualityIssue
from app.services.canonical_market_service import _source, close_series, reconcile_market_observations
from app.services.ingestion_lock import lock_ingestion_writes
from app.services.market_providers import DpsMarketDataProvider, _dps_decimal

INDEXES = {'KSE100': 'total_return', 'KSE100PR': 'price_return'}


def import_index_month(db, symbol, month, client, store=None):
    if symbol not in INDEXES:
        raise ValueError('Only KSE100 and KSE100PR are supported')
    response = client.post('/historical', data={'symbol': symbol, 'year': str(month.year), 'month': str(month.month)})
    response.raise_for_status()
    # Reject invalid rows rather than silently calling a partly parsed month complete.
    from bs4 import BeautifulSoup
    table = BeautifulSoup(response.text, 'html.parser').find('table', id='historicalTable')
    rows = DpsMarketDataProvider.parse_symbol_history(response.text, symbol)
    populated = [tr for tr in table.find_all('tr') if len(tr.find_all('td')) == 6]
    closes = {}
    source_rows = {}
    for tr in populated:
        cells = [td.get_text(' ', strip=True) for td in tr.find_all('td')]
        day = datetime.strptime(cells[0], '%b %d, %Y').date()
        close = _dps_decimal(cells[4])
        if day in source_rows:
            if source_rows[day] == cells:
                continue
            raise ValueError(f'Conflicting DPS index rows for {day}')
        if day.year != month.year or day.month != month.month or close is None or close <= 0:
            raise ValueError('DPS index month contains invalid or out-of-window close rows')
        source_rows[day] = cells
        closes[day] = close
    rows = list({row.trade_date:row for row in rows}.values())
    lock_ingestion_writes(db, 'market-price-write')
    source = _source(db, 'dps')
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
    if instrument is None:
        instrument = Instrument(symbol=symbol, name=f'PSX {symbol}', instrument_type='total_return_index' if symbol=='KSE100' else 'index', currency='PKR', country='PK', metadata_json=json.dumps({'broad_market_proxy': True, 'return_basis': INDEXES[symbol], 'identity_source': 'dps', 'data_classification': 'observed'}))
        db.add(instrument); db.flush()
    elif instrument.instrument_type not in ('index', 'total_return_index'):
        raise ValueError('Index symbol conflicts with an existing non-index instrument')
    stored = (store or get_artifact_store()).put(response.content, '.html')
    request = f'{symbol}:{month:%Y-%m}'
    fingerprint = sha256(request.encode()).hexdigest()
    artifact = db.scalar(select(SourceArtifact).where(SourceArtifact.data_source_id==source.id, SourceArtifact.request_fingerprint==fingerprint, SourceArtifact.sha256==stored.sha256))
    if artifact is None:
        artifact = SourceArtifact(data_source_id=source.id, source_url=f'https://dps.psx.com.pk/historical?symbol={symbol}&year={month.year}&month={month.month}', http_method='POST', request_fingerprint=fingerprint, sha256=stored.sha256, storage_path=stored.storage_path, content_type=response.headers.get('content-type'), parser_version='dps-index-month-v1', status='parsed', response_metadata_json=json.dumps({'bytes':stored.bytes,'symbol':symbol,'month':f'{month:%Y-%m}','return_basis':INDEXES[symbol]}))
        db.add(artifact); db.flush()
    previous = close_series(db, symbol, end=month.fromordinal(month.toordinal()-1))
    prior = previous[max(previous)] if previous else None
    for day, close in sorted(closes.items()):
        stamp = datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo('Asia/Karachi'))
        values = {'trade_date':str(day),'close':str(close),'return_basis':INDEXES[symbol]}
        if not db.scalar(select(MarketObservation.id).where(MarketObservation.instrument_id==instrument.id,MarketObservation.effective_at==stamp,MarketObservation.artifact_id==artifact.id,MarketObservation.frequency=='daily_close')):
            db.add(MarketObservation(instrument_id=instrument.id,effective_at=stamp,frequency='daily_close',values_json=json.dumps(values,sort_keys=True),currency='PKR',unit='index_points',adjustment_state='index_published',artifact_id=artifact.id))
    rejected_dates=set(closes)-{r.trade_date for r in rows}
    for day in rejected_dates:
        if not db.scalar(select(DataQualityIssue.id).where(DataQualityIssue.artifact_id==artifact.id,DataQualityIssue.rule=='index_ohlc_rejected_close_retained',DataQualityIssue.details_json.contains(str(day)))):
            db.add(DataQualityIssue(artifact_id=artifact.id,rule='index_ohlc_rejected_close_retained',severity='warning',selection_status='partial',details_json=json.dumps({'symbol':symbol,'trade_date':str(day),'accepted_fields':['close'],'rejected_fields':['open','high','low'],'reason':'DPS OHLC validation failed; valid positive dated close retained separately'})))
    written = 0
    for row in rows:
        stamp = datetime.combine(row.trade_date, datetime.min.time(), tzinfo=ZoneInfo('Asia/Karachi'))
        values = {'trade_date':str(row.trade_date),'open':str(row.open),'high':str(row.high),'low':str(row.low),'close':str(row.close),'volume':row.volume,'return_basis':INDEXES[symbol]}
        if prior is not None: values['previous_close']=str(prior)
        observation = db.scalar(select(MarketObservation).where(MarketObservation.instrument_id==instrument.id,MarketObservation.effective_at==stamp,MarketObservation.artifact_id==artifact.id,MarketObservation.frequency=='daily'))
        if observation is None:
            db.add(MarketObservation(instrument_id=instrument.id,effective_at=stamp,frequency='daily',values_json=json.dumps(values,sort_keys=True),currency='PKR',unit='index_points',adjustment_state='index_published',artifact_id=artifact.id))
            written+=1
        prior=row.close
    db.flush()
    
    for day in closes:
        reconcile_market_observations(db,instrument_id=instrument.id,effective_at=datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo('Asia/Karachi')))
    return {'symbol':symbol,'month':f'{month:%Y-%m}','rows':len(closes),'ohlc_rows':len(rows),'rejected_ohlc_rows':len(rejected_dates),'written':written,'artifact_id':artifact.id,'return_basis':INDEXES[symbol]}
