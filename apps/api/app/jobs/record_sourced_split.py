"""Record one source-reviewed split from retained report text; no guessed actions."""
import argparse,json,re
from datetime import date
from decimal import Decimal
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.document import Document,DocumentPage
from app.models.workstation import CorporateAction,Instrument


def record_split(db,document_id,page_number,symbol,effective_date,old_shares,new_shares,quote):
    document=db.get(Document,document_id)
    page=db.scalar(select(DocumentPage).where(DocumentPage.document_id==document_id,DocumentPage.page_number==page_number))
    instrument=db.scalar(select(Instrument).where(Instrument.symbol==symbol))
    if not document or document.symbol!=symbol or not document.artifact_id or not page or not instrument:
        raise ValueError('Split requires a retained sourced report page for the same instrument')
    normalized=lambda text:re.sub(r'\s+',' ',text).strip()
    if len(quote)<30 or normalized(quote) not in normalized(page.text):raise ValueError('Evidence quote must match the retained page')
    old,new=Decimal(str(old_shares)),Decimal(str(new_shares))
    if not old.is_finite() or not new.is_finite() or min(old,new)<=0:raise ValueError('Split ratio must be positive and finite')
    # Quote is source-reviewed, not inferred from a price jump. Ratio/date also
    # must occur in it; this protects against transcription errors.
    text=normalized(quote).replace('–','-').replace('—','-')
    ratio=f'{new:g}-for-{old:g}'
    date_text=f'{effective_date:%B} {effective_date.day}, {effective_date.year}'
    if ratio not in text or date_text not in text:raise ValueError('Quote does not support the supplied ratio and effective date')
    existing=db.scalar(select(CorporateAction).where(CorporateAction.instrument_id==instrument.id,CorporateAction.action_type=='stock_split',CorporateAction.effective_date==effective_date))
    details={'old_shares':str(old),'new_shares':str(new),'split_multiplier':str(new/old),'verification':'source_reviewed','document_id':document_id,'page_number':page_number,'quote':quote,'source_url':document.source_url}
    if existing:
        previous=json.loads(existing.details_json)
        if Decimal(previous['old_shares'])!=old or Decimal(previous['new_shares'])!=new:raise ValueError('Conflicting recorded split ratio')
        return existing
    action=CorporateAction(instrument_id=instrument.id,action_type='stock_split',effective_date=effective_date,ex_date=effective_date,artifact_id=document.artifact_id,details_json=json.dumps(details))
    db.add(action);db.flush();return action


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--document-id',required=True);p.add_argument('--page',type=int,required=True);p.add_argument('--symbol',required=True)
    p.add_argument('--effective-date',type=date.fromisoformat,required=True);p.add_argument('--old-shares',type=Decimal,required=True);p.add_argument('--new-shares',type=Decimal,required=True);p.add_argument('--quote',required=True)
    a=p.parse_args()
    with SessionLocal() as db:
        action=record_split(db,a.document_id,a.page,a.symbol.upper(),a.effective_date,a.old_shares,a.new_shares,a.quote);db.commit();print(json.dumps({'action_id':action.id,'symbol':a.symbol,'effective_date':str(action.effective_date)}))


if __name__=='__main__':main()
