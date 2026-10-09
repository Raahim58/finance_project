"""Current quotes are intraday observations; they never overwrite daily history."""
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import json
import re
from bs4 import BeautifulSoup
from sqlalchemy import select
from app.models.workstation import Instrument, MarketObservation
from app.services.market_providers import DpsMarketDataProvider
from app.services.ingestion_persistence import source, store_artifact
from app.services.pipeline.scheduling import price_bucket


def parse_market_watch(html):
    soup=BeautifulSoup(html,'html.parser');quotes=[];seen=set()
    for table in soup.find_all('table'):
        headers=[' '.join(t.get_text(' ',strip=True).upper().split()) for t in table.select('thead th')]
        if not {'SYMBOL','LDCP','CURRENT','OPEN','HIGH','LOW','VOLUME'}.issubset(headers): continue
        # Do not ingest futures/odd-lot sections as regular equities.
        ancestor=table.find_parent(id=True)
        marker=str(ancestor.get('id','')).lower() if ancestor else ''
        if marker and any(value in marker for value in ('future','odd','bond')): continue
        for row in table.select('tbody tr'):
            cells=[t.get_text(' ',strip=True) for t in row.find_all('td')]
            if len(cells)!=len(headers): continue
            values=dict(zip(headers,cells));symbol=values['SYMBOL'].split()[0].upper()
            if symbol in seen: continue
            try:
                nums={key:Decimal(values[label].replace(',','')) for key,label in
                    (('close','CURRENT'),('previous_close','LDCP'),('open','OPEN'),('high','HIGH'),('low','LOW'))}
                volume=int(values['VOLUME'].replace(',',''))
            except (InvalidOperation,ValueError): continue
            if any(not v.is_finite() or v<0 for v in nums.values()) or volume<0: continue
            if nums['close']<=0 or nums['previous_close']<=0: continue
            # Published positive quotes with zero trades can have zero OHLC.
            # Preserve the source zeros; never synthesize an opening/high/low.
            untraded = volume == 0 and all(nums[k] == 0 for k in ('open','high','low'))
            if not untraded and (nums['open']<=0 or nums['low']<=0 or nums['high']<max(nums['open'],nums['close']) or nums['low']>min(nums['open'],nums['close'])): continue
            quotes.append({'symbol':symbol,**{k:str(v) for k,v in nums.items()},'volume':volume});seen.add(symbol)
    if not quotes: raise ValueError('market_watch_contract_changed_or_empty')
    return quotes


def parse_live_indices(html):
    """Published trading-panel levels/change/volume/value, not invented OHLC."""
    output = []; seen = set()
    for tr in BeautifulSoup(html, 'html.parser').find_all('tr'):
        cells = tr.find_all('td')
        if len(cells) != 7: continue
        values = [c.get_text(' ', strip=True) for c in cells]
        symbol = values[0]
        if symbol not in ('KSE100', 'KSE100PR') or symbol in seen: continue
        match = re.fullmatch(r'([+-]?[\d,]+(?:\.\d+)?)\s*\(([+-]?[\d,]+(?:\.\d+)?)%\)', values[4])
        if not match: continue
        try:
            close, high, low = [Decimal(v.replace(',', '')) for v in values[1:4]]
            change, percent = [Decimal(v.replace(',', '')) for v in match.groups()]
            volume = int(values[5].replace(',', '')); value = Decimal(values[6].replace(',', ''))
            if 'change__text--neg' in cells[4].get('class', []):
                change, percent = -abs(change), -abs(percent)
        except (InvalidOperation, ValueError): continue
        if not all(v.is_finite() for v in (close, high, low, change, percent, value)): continue
        if close <= 0 or not low <= close <= high or volume < 0 or value < 0: continue
        output.append({'symbol': symbol, 'close': str(close), 'high': str(high), 'low': str(low),
                       'change': str(change), 'change_percent': str(percent), 'volume': volume, 'value': str(value)})
        seen.add(symbol)
    return output


def refresh(db, *, now=None,symbols=None):
    now=now or datetime.now(UTC)
    bucket,basis=price_bucket(db,now)
    if not bucket: return {'status':'outside_regular_session'}
    provider=DpsMarketDataProvider()
    with provider._client() as client:
        panel=client.get('/trading-panel');panel.raise_for_status()
        state=regular_market_state(panel.text)
        if state!='open': return {'status':'exchange_not_open','source_market_state':state}
        universe_response=client.get('/symbols');universe_response.raise_for_status()
        universe=provider.parse_symbols(universe_response.json())
        response=client.get('/market-watch');response.raise_for_status()
    rows=parse_market_watch(response.text)
    publisher=source(db,'PSX DPS market watch','market','https://dps.psx.com.pk',10,120,
        'Regular intraday quote snapshot. Time basis is retrieval time where no source timestamp exists.')
    publisher.freshness_sla_minutes = 120
    index_source = source(db, 'PSX DPS trading panel', 'market', 'https://dps.psx.com.pk', 10, 120,
        'Published index snapshot during an open regular session; observation timestamp is retrieval time.')
    index_source.freshness_sla_minutes = 120
    panel_artifact = store_artifact(db, index_source, panel.content, url=str(panel.url), method='GET',
        parser_version='dps-trading-panel-v1', content_type='text/html', effective_at=now)
    indices = parse_live_indices(panel.text)
    for row in indices:
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == row['symbol']))
        if instrument is None: continue
        if db.scalar(select(MarketObservation.id).where(MarketObservation.instrument_id == instrument.id,
            MarketObservation.frequency == 'index_intraday', MarketObservation.effective_at == now,
            MarketObservation.artifact_id == panel_artifact.id)): continue
        db.add(MarketObservation(instrument_id=instrument.id, artifact_id=panel_artifact.id,
            effective_at=now, frequency='index_intraday', values_json=json.dumps(row),
            unit='index_points', adjustment_state='unadjusted', is_selected=True))
    store_artifact(db,publisher,universe_response.content,url=str(universe_response.url),method='GET',
        parser_version=provider.parser_version,content_type='application/json',effective_at=now)
    from app.services.market_ingestion import sync_observed_dps_universe
    sync_observed_dps_universe(db,universe)
    artifact=store_artifact(db,publisher,response.content,url=str(response.url),method='GET',
        parser_version='dps-market-watch-v1',content_type='text/html',effective_at=now)
    instruments={i.symbol:i for i in db.scalars(select(Instrument).where(Instrument.instrument_type=='equity',Instrument.active_to.is_(None)))}
    count=0
    for row in rows:
        if symbols and row['symbol'] not in symbols: continue
        instrument=instruments.get(row.pop('symbol'))
        if not instrument: continue
        observation=db.scalar(select(MarketObservation).where(MarketObservation.instrument_id==instrument.id,
            MarketObservation.effective_at==now,MarketObservation.frequency=='intraday',MarketObservation.artifact_id==artifact.id))
        if observation: continue
        row.update(source='dps',quality_status='observed_intraday',timestamp_basis='retrieved_at',calendar_basis=basis)
        db.add(MarketObservation(instrument_id=instrument.id,effective_at=now,frequency='intraday',
            values_json=json.dumps(row),currency='PKR',unit='price',adjustment_state='unadjusted',artifact_id=artifact.id,is_selected=True))
        count+=1
    from app.models.pipeline import SourceTarget
    metadata = json.loads(artifact.response_metadata_json or '{}')
    artifact.response_metadata_json = json.dumps({**metadata,
        'quote_scope': 'symbol_subset' if symbols else 'all_regular_equities',
        'accepted_quotes': count, 'source_rows': len(rows)})
    numeric=source(db,'PSX pipeline numeric targets','market','https://dps.psx.com.pk',10,120,'Target configuration; not data provenance.')
    price_target=db.scalar(select(SourceTarget).where(SourceTarget.adapter_key=='prices',SourceTarget.enabled.is_(True)))
    if price_target and not symbols:
        scopes=set(db.scalars(select(SourceTarget.scope_key).where(SourceTarget.data_source_id==numeric.id)))
        for inst in instruments.values():
            scope='reports:'+inst.symbol
            if scope not in scopes:
                db.add(SourceTarget(data_source_id=numeric.id,instrument_id=inst.id,scope_key=scope,adapter_key='reports',schedule='announcements',enabled=True))
    db.flush();return {'status':'completed' ,'quotes':count,'indices':len(indices),'timestamp_basis':'retrieved_at','calendar_basis':basis}


def regular_market_state(html):
    soup=BeautifulSoup(html,'html.parser')
    for row in soup.find_all('tr'):
        cells=[c.get_text(' ',strip=True).lower() for c in row.find_all(['td','th'])]
        if len(cells)>=2 and cells[0]=='regular':
            if cells[1] in ('open','closed','halted','suspended','pre-open'): return cells[1]
            raise ValueError('unknown_regular_market_state')
    raise ValueError('regular_market_state_contract_missing')
