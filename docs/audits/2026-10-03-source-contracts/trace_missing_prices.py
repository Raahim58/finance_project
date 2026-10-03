"""Read-only trace of the 247 active records without prices; no queue writes."""
import json
from datetime import date
from bs4 import BeautifulSoup
from sqlalchemy import text
from app.db.session import SessionLocal
from app.ingestion.artifact_store import get_artifact_store
from app.services.market_providers import DpsMarketDataProvider

def emit(check, rows):
    print(json.dumps(dict(check=check, rows=rows), default=str), flush=True)

with SessionLocal() as db:
    db.execute(text('SET TRANSACTION READ ONLY'))
    missing = [dict(r) for r in db.execute(text("select c.symbol,c.name,(select count(*) from ingestion_coverage cv where cv.instrument_id=i.id and cv.dataset_type='price_history') history_units,(select count(*) from ingestion_coverage cv where cv.instrument_id=i.id and cv.dataset_type='price_history' and cv.status='failed') failed_history_units from companies c join instruments i on i.company_id=c.id where c.is_active and not exists(select 1 from market_prices p where p.company_id=c.id) order by c.symbol")).mappings()]
    emit('missing_company_history', missing)
    emit('summary', dict(missing=len(missing), never_queued_for_history=sum(r['history_units']==0 for r in missing), attempted_history=sum(r['history_units']>0 for r in missing), named_rights=sum('right' in r['name'].lower() for r in missing)))
    candidates = [dict(r) for r in db.execute(text("select id,source_url,storage_path,sha256,effective_at,retrieved_at from source_artifacts where source_url like 'https://dps.psx.com.pk/historical%' and effective_at>='2026-08-12' and effective_at<'2026-08-14' order by retrieved_at desc limit 5")).mappings()]
    universe = [dict(r) for r in db.execute(text("select id,storage_path,sha256,retrieved_at from source_artifacts where source_url='https://dps.psx.com.pk/symbols' order by retrieved_at desc limit 1")).mappings()]
store = get_artifact_store()
if universe:
    a=universe[0]
    try:
        raw=store.get(a['storage_path'])
        parsed=DpsMarketDataProvider.parse_symbols(json.loads(raw))
        mapped={r['symbol']:r for r in parsed}
        emit('original_universe', dict(artifact_id=a['id'],sha256=a['sha256'],retrieved_at=a['retrieved_at'],symbols=len(parsed),missing_records_in_universe=sum(r['symbol'] in mapped for r in missing),missing_rows=[mapped[r['symbol']] for r in missing if r['symbol'] in mapped]))
    except Exception as exc:
        emit('original_universe_error',dict(artifact_id=a['id'],error_type=type(exc).__name__,message=str(exc)[:200]))
else:
    emit('original_universe_error',dict(reason='No retained /symbols artifact found'))
found=False
for a in candidates:
    try:
        raw=store.get(a['storage_path'])
        soup=BeautifulSoup(raw,'html.parser')
        table=soup.find('table',id='historicalTable')
        if table is None: continue
        headers=[c.get_text(' ',strip=True).upper() for c in table.find_all('th')]
        if not headers or headers[0]!='SYMBOL': continue
        raw_symbols={cells[0].get_text(' ',strip=True).upper() for tr in table.find_all('tr')[1:] if (cells:=tr.find_all('td'))}
        issues=[]
        accepted={r.symbol for r in DpsMarketDataProvider.parse_datewise_history(str(soup),date(2026,8,13),issues)}
        emit('original_daily_response',dict(artifact_id=a['id'],sha256=a['sha256'],effective_at=a['effective_at'],retrieved_at=a['retrieved_at'],raw_symbols=len(raw_symbols),parsed_symbols=len(accepted),missing_absent_from_response=[r['symbol'] for r in missing if r['symbol'] not in raw_symbols],missing_present_but_rejected=[r['symbol'] for r in missing if r['symbol'] in raw_symbols and r['symbol'] not in accepted],missing_present_and_accepted=[r['symbol'] for r in missing if r['symbol'] in accepted],quality_issues=issues))
        found=True
        break
    except Exception as exc:
        emit('original_daily_response_error',dict(artifact_id=a['id'],error_type=type(exc).__name__,message=str(exc)[:200]))
if not found: emit('original_daily_response_unavailable',candidates)
