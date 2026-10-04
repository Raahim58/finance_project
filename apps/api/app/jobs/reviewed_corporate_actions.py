"""Import operator-reviewed actions from pinned official PDFs; never infer from prices."""
import argparse
import io
import json
import re
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from urllib.parse import urlparse

from pypdf import PdfReader
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.workstation import CorporateAction, Instrument
from app.services.canonical_market_service import _source
from app.services.ingestion_lock import lock_ingestion_writes
from app.services.ingestion_persistence import store_artifact
from app.services.market_providers import DpsMarketDataProvider


def normalized(value):
    return re.sub(r'\s+', ' ', value).strip()


def import_reviewed_action(db, client, item):
    if item['action_type'] not in ('stock_split', 'bonus_issue', 'cash_dividend'):
        raise ValueError('Unsupported reviewed action type')
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == item['symbol']))
    if instrument is None:
        raise ValueError('Reviewed action requires an existing instrument identity')
    ex_date = date.fromisoformat(item['ex_date'])
    evidence = []
    for proof in item['evidence']:
        url = urlparse(proof['url'])
        if url.scheme != 'https' or url.hostname != 'dps.psx.com.pk' or not url.path.startswith('/download/'):
            raise ValueError('Reviewed action requires an official DPS download')
        response = client.get(proof['url']); response.raise_for_status()
        if len(response.content) > 20_000_000 or sha256(response.content).hexdigest() != proof['sha256']:
            raise ValueError('Reviewed source digest changed; review again before importing')
        page = PdfReader(io.BytesIO(response.content)).pages[proof['page'] - 1].extract_text()
        if len(proof['quote']) < 30 or normalized(proof['quote']) not in normalized(page):
            raise ValueError('Reviewed quote does not match the pinned official page')
        artifact = store_artifact(db, _source(db, 'dps'), response.content, url=proof['url'],
            method='GET', parser_version='dps-reviewed-action-v1', content_type='application/pdf')
        evidence.append({**proof, 'artifact_id': artifact.id})
    if not evidence:
        raise ValueError('Action requires dated source evidence')
    # Explicit reviewed evidence supports the ex date independently of delivery.
    if item['date_evidence'] not in normalized(' '.join(p['quote'] for p in evidence)):
        raise ValueError('Ex-date evidence is absent')
    supported_date = None
    for pattern in ('%B %d, %Y', '%d-%b-%Y', '%Y-%m-%d'):
        try:
            supported_date = datetime.strptime(item['date_evidence'], pattern).date(); break
        except ValueError:
            pass
    if supported_date != ex_date:
        raise ValueError('Ex date differs from the reviewed date evidence')
    details = {**item, 'evidence': evidence, 'verification': 'source_reviewed',
        'source_url': evidence[0]['url'], 'application_scope': 'historical_analytics_only'}
    if item['action_type'] in ('stock_split', 'bonus_issue'):
        old, new = Decimal(item['old_shares']), Decimal(item['new_shares'])
        if not old.is_finite() or not new.is_finite() or min(old, new) <= 0:
            raise ValueError('Invalid reviewed ratio')
        if item['ratio_evidence'] not in normalized(' '.join(p['quote'] for p in evidence)):
            raise ValueError('Ratio evidence is absent')
        if item['action_type'] == 'bonus_issue':
            percent = re.fullmatch(r'(\d+(?:\.\d+)?)%\s*\(B\)', item['ratio_evidence'])
            expected = Decimal(1) + Decimal(percent.group(1)) / 100 if percent else None
        else:
            faces = re.fullmatch(r'Rs\.\s*(\d+(?:\.\d+)?)/- to Rs\.\s*(\d+(?:\.\d+)?)/-', item['ratio_evidence'])
            expected = Decimal(faces.group(1)) / Decimal(faces.group(2)) if faces and Decimal(faces.group(2)) > 0 else None
        if expected != new / old:
            raise ValueError('Share multiplier differs from reviewed source evidence')
        details['split_multiplier'] = str(new / old)
    else:
        amount = Decimal(item['cash_per_share'])
        if not amount.is_finite() or amount <= 0 or item['amount_evidence'] not in normalized(' '.join(p['quote'] for p in evidence)):
            raise ValueError('Invalid or unsupported cash dividend')
    if item.get('payment_date'):
        raise ValueError('Payment-date import needs a separate verified payment contract')
    lock_ingestion_writes(db, 'corporate-action-write')
    existing = db.scalar(select(CorporateAction).where(CorporateAction.instrument_id == instrument.id,
        CorporateAction.action_type == item['action_type'], CorporateAction.ex_date == ex_date))
    if existing:
        previous = json.loads(existing.details_json)
        keys = ('old_shares', 'new_shares') if item['action_type'] != 'cash_dividend' else ('cash_per_share',)
        if any(Decimal(previous[k]) != Decimal(item[k]) for k in keys):
            raise ValueError('Conflicting reviewed action; existing record preserved')
        return existing
    action = CorporateAction(instrument_id=instrument.id, action_type=item['action_type'],
        effective_date=ex_date, ex_date=ex_date, artifact_id=evidence[0]['artifact_id'],
        payment_date=date.fromisoformat(item['payment_date']) if item.get('payment_date') else None,
        details_json=json.dumps(details, sort_keys=True))
    db.add(action); db.flush()
    return action


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    with open(args.manifest) as source:
        items = json.load(source)
    with DpsMarketDataProvider()._client() as client:
        for item in items:
            with SessionLocal() as db:
                action = import_reviewed_action(db, client, item); db.commit()
                print(json.dumps({'symbol': item['symbol'], 'action_id': action.id,
                    'type': action.action_type, 'ex_date': str(action.ex_date)}), flush=True)


if __name__ == '__main__':
    main()
