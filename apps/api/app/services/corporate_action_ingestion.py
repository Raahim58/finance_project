"""Official payout announcements. Announcement/book closure is not an ex/payment date."""
import json
import re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from sqlalchemy import select

from app.models.workstation import CorporateAction, DataQualityIssue, Instrument
from app.services.canonical_market_service import _source
from app.services.ingestion_lock import lock_ingestion_writes
from app.services.ingestion_persistence import store_artifact

HEADERS = ['Symbol','Company','Sector','Dividend Announcement','Date / Time of Announcement','Book Closure Date']


def parse_payouts(html):
    soup=BeautifulSoup(html,'html.parser')
    table=soup.find('table',id='announcementsTable')
    if table is None or [h.get_text(' ',strip=True) for h in table.find_all('th')]!=HEADERS:
        raise ValueError('DPS payout table contract changed')
    count=re.search(r'of\s+([\d,]+)\s+entries',soup.get_text(' ',strip=True))
    if count is None:raise ValueError('DPS payout pagination total missing')
    records,issues=[],[]
    for tr in table.find_all('tr'):
        cells=[c.get_text(' ',strip=True) for c in tr.find_all('td')]
        if len(cells)!=6:continue
        try:
            announced=datetime.strptime(cells[4],'%B %d, %Y %I:%M %p').replace(tzinfo=ZoneInfo('Asia/Karachi'))
            closure=[datetime.strptime(d,'%d/%m/%Y').date().isoformat()
                for d in re.findall(r'\d{2}/\d{2}/\d{4}',cells[5])]
            components=re.findall(r'(\d+(?:\.\d+)?)\s*%\s*(?:\(\s*[iIvVfF]+\s*\)\s*)?\(([DBR])\)',cells[3])
            if not components:
                named = re.fullmatch(r'DIVIDEND\s*=\s*(\d+(?:\.\d+)?)\s*%\s*(?:\(\s*[iIvVfF]+\s*\))?', cells[3], re.I)
                if named:
                    components = [(named.group(1), 'D')]
            if not components:
                issues.append({'symbol':cells[0],'announcement':cells[3],'reason':'unsupported_or_nil_payout'})
            for amount,kind in components:
                percent=Decimal(amount)
                if percent<=0:continue
                records.append({'symbol':cells[0].strip().upper(),'announced_at':announced.isoformat(),
                    'payout_percent':str(percent),'kind':kind,'book_closure_dates':closure,
                    'published_text':cells[3],'quote':' | '.join(cells),
                    'verification':'sourced_announcement','ex_date_status':'not_supplied',
                    'payment_date_status':'not_supplied'})
        except ValueError as exc:
            issues.append({'symbol':cells[0],'reason':str(exc),'quote':' | '.join(cells)})
    return records,int(count.group(1).replace(',','')),issues


def import_payout_page(db,client,offset=0,count=100):
    if offset<0 or not 1<=count<=100:raise ValueError('Invalid bounded payout page')
    response=client.post('/payouts',data={'symbol':'','count':str(count),'offset':str(offset)})
    response.raise_for_status()
    records,total,issues=parse_payouts(response.text)
    lock_ingestion_writes(db,'corporate-action-write')
    url=f'https://dps.psx.com.pk/payouts?count={count}&offset={offset}'
    artifact=store_artifact(db,_source(db,'dps'),response.content,url=url,method='POST',
        parser_version='dps-payout-announcement-v1',content_type='text/html')
    instruments={i.symbol:i for i in db.scalars(select(Instrument).where(Instrument.symbol.in_({r['symbol'] for r in records})))}
    written,unmatched=0,set()
    for record in records:
        instrument=instruments.get(record['symbol'])
        if not instrument:unmatched.add(record['symbol']);continue
        action_type={'D':'cash_dividend_announced','B':'bonus_issue_announced','R':'rights_issue_announced'}[record['kind']]
        day=datetime.fromisoformat(record['announced_at']).date()
        existing=db.scalars(select(CorporateAction).where(CorporateAction.instrument_id==instrument.id,
            CorporateAction.action_type==action_type,CorporateAction.effective_date==day)).all()
        identity=(record['announced_at'],record['payout_percent'],record['published_text'])
        if any(tuple(json.loads(a.details_json).get(k) for k in ('announced_at','payout_percent','published_text'))==identity for a in existing):continue
        if any(json.loads(a.details_json).get('announced_at') == record['announced_at'] for a in existing):
            issues.append({'symbol':record['symbol'],'reason':'conflicting_revision_requires_review','quote':record['quote']})
            continue
        details={**record,'source_url':url,'lifecycle':'announced',
            'missing_execution_fields':['verified_ex_date','verified_payment_date_or_delivery_date'],
            'cash_per_share':None}
        # No assumed face value or settlement calendar. These rows cannot be
        # applied by the ledger or historical-price adjustment functions.
        db.add(CorporateAction(instrument_id=instrument.id,action_type=action_type,
            effective_date=day,artifact_id=artifact.id,details_json=json.dumps(details,sort_keys=True)))
        db.flush();written+=1
    for issue in issues:
        serialized=json.dumps(issue,sort_keys=True)
        if not db.scalar(select(DataQualityIssue.id).where(DataQualityIssue.artifact_id==artifact.id,
            DataQualityIssue.rule=='unsupported_dps_payout',DataQualityIssue.details_json==serialized)):
            db.add(DataQualityIssue(artifact_id=artifact.id,rule='unsupported_dps_payout',severity='warning',
                details_json=serialized,selection_status='not_applied'))
    return {'offset':offset,'total_source_rows':total,'records':len(records),'written':written,
        'unmatched_symbols':sorted(unmatched),'issues':issues,'artifact_id':artifact.id,
        'execution_ready':False,'next_offset':offset+count if offset+count<total else None}
