"""Sourced split/bonus historical views. Stored observations and holdings stay raw."""
import json
from dataclasses import replace
from decimal import Decimal
from sqlalchemy import select
from app.models.workstation import CorporateAction
from app.services.canonical_market_service import price_series


def verified_splits(db, instrument_id, as_of):
    actions=[]
    for action in db.scalars(select(CorporateAction).where(CorporateAction.instrument_id==instrument_id,CorporateAction.action_type.in_(['stock_split','bonus_issue']),CorporateAction.effective_date<=as_of).order_by(CorporateAction.effective_date)):
        details=json.loads(action.details_json)
        if not action.artifact_id or details.get('verification')!='source_reviewed':continue
        old,new=Decimal(str(details['old_shares'])),Decimal(str(details['new_shares']))
        if not old.is_finite() or not new.is_finite() or min(old,new)<=0:raise ValueError('Invalid sourced split ratio')
        actions.append((action,new/old))
    return actions


def split_adjusted_price_series(db,symbol,start=None,end=None,*,raw_rows=None,**kwargs):
    rows=raw_rows if raw_rows is not None else price_series(db,symbol,start,end,**kwargs)
    if not rows or not rows[0].instrument_id:return rows
    actions=verified_splits(db,rows[0].instrument_id,end or rows[-1].trade_date)
    if not actions:return rows
    adjusted=[]
    for row in rows:
        # Never reapply to data supplied in an already adjusted basis.
        if row.adjustment_state not in ('unadjusted','sourced_split_adjusted'):
            adjusted.append(row);continue
        if row.adjustment_state=='sourced_split_adjusted':
            adjusted.append(row);continue
        factor=Decimal(1)
        for action,ratio in actions:
            if row.trade_date<action.effective_date:factor*=ratio
        previous=row.previous_close/factor
        # On the first post-split day, use the actually observed prior close in
        # the same adjusted basis, not a provider's potentially raw previous_close.
        if adjusted and any(adjusted[-1].trade_date < action.effective_date <= row.trade_date for action,_ in actions):previous=adjusted[-1].close
        adjusted.append(replace(row,open=row.open/factor,high=row.high/factor,low=row.low/factor,close=row.close/factor,previous_close=previous,
            adjustment_state='sourced_split_adjusted'))
    return adjusted
