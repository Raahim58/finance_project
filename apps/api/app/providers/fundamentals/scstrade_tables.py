"""SCSTrade secondary tables: issuer-isolated sessions, raw capture, no guessed units."""
from dataclasses import dataclass
import time
import httpx

BASE='https://www.scstrade.com/stockscreening/SS_CompanySnapShotYFNew.aspx'
TABLES=('IncomeStatement','BalanceSheet','CashFlow')

@dataclass(frozen=True)
class SecondaryTableCapture:
    symbol:str
    table:str
    request_url:str
    request_scope:dict
    content:bytes
    content_type:str

class ScsTradeTablesProvider:
    parser_version='scstrade-secondary-tables-v1'
    def __init__(self, *, transport=None): self.transport=transport

    def fetch(self,symbol):
        symbol=symbol.strip().upper()
        if not symbol or len(symbol)>30 or not all(c.isalnum() or c in '.-' for c in symbol): raise ValueError('invalid_issuer_symbol')
        # The endpoint can return the previous session's issuer despite sym.
        # Never reuse one issuer's initialized cookie jar for another issuer.
        with httpx.Client(timeout=30,follow_redirects=True,transport=self.transport,
                headers={'User-Agent':'psx-ai-portfolio-agent/0.1 (low-rate research)'}) as client:
            page=client.get(BASE,params={'symbol':symbol});page.raise_for_status()
            captures=[]
            for table in TABLES:
                scope={'sym':symbol,'_search':False,'rows':100,'page':1,'sidx':'Year / Quarter','sord':'desc'}
                response=client.post(BASE+'/'+table,json={**scope,'nd':int(time.time()*1000)},
                    headers={'Content-Type':'application/json; charset=utf-8','X-Requested-With':'XMLHttpRequest','Referer':str(page.url)})
                response.raise_for_status()
                if len(response.content)>5*1024*1024: raise ValueError('secondary_table_response_too_large')
                response.json()  # Only a transport-shape check; not financial validation.
                captures.append(SecondaryTableCapture(symbol,table,str(response.url),scope,response.content,response.headers.get('content-type','application/json')))
        return captures
