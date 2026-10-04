"""Dated official shares/capitalization; index-specific shares are not total shares."""
import io
import json
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select

from app.models.workstation import DataQualityIssue, Instrument, MarketObservation, SourceArtifact
from app.services.canonical_market_service import _source, reconcile_market_observations
from app.services.ingestion_lock import lock_ingestion_writes
from app.services.ingestion_persistence import store_artifact
from app.services.market_numbers import safe_decimal

HEADERS = ['ISIN', 'SYMBOL', 'COMPANY', 'PRICE', 'IDX WT %', 'FF BASED SHARES',
           'FF BASED MCAP', 'ORD SHARES', 'ORD SHARES MCAP', 'VOLUME']


def parse_constituents(content):
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, dtype=str, keep_default_na=False)
    if 'KSE-ALL-Shares' not in sheets:
        raise ValueError('DPS workbook lacks the authoritative all-shares sheet')
    snapshots, weights, issues = {}, {}, []
    for name, frame in sheets.items():
        if list(frame.columns) != HEADERS:
            raise ValueError(f'DPS constituent headers changed for {name}')
        seen = set()
        for values in frame.itertuples(index=False, name=None):
            symbol = str(values[1]).strip().upper()
            if not symbol:
                continue
            if symbol in seen:
                raise ValueError(f'Duplicate constituent {symbol} in {name}')
            seen.add(symbol)
            weight = safe_decimal(values[4])
            if weight is not None and 0 <= weight <= 100:
                weights.setdefault(symbol, {})[name] = str(weight)
            if name != 'KSE-ALL-Shares':
                continue
            price, free, free_cap, ordinary, cap, volume = [safe_decimal(values[i]) for i in (3,5,6,7,8,9)]
            if (any(v is None or not v.is_finite() or v < 0 for v in (price,free,free_cap,ordinary,cap,volume))
                or ordinary <= 0 or free > ordinary
                or any(v != v.to_integral_value() for v in (free,ordinary,volume))):
                issues.append({'symbol':symbol,'reason':'invalid_shares_price_or_capitalization'})
                continue
            if (abs(cap-price*ordinary) > max(Decimal(1),cap*Decimal('0.00000001'))
                or abs(free_cap-price*free) > max(Decimal(1),free_cap*Decimal('0.00000001'))):
                issues.append({'symbol':symbol,'reason':'published_capitalization_inconsistent_with_shares_and_price'})
                continue
            snapshots[symbol] = {'isin':str(values[0]), 'reference_price':str(price),
                'ordinary_shares':str(ordinary), 'free_float_shares':str(free),
                'market_cap':str(cap), 'free_float_market_cap':str(free_cap),
                'volume':int(volume), 'share_basis':'KSE-ALL-Shares ordinary shares', 'currency':'PKR'}
    for symbol, snapshot in snapshots.items():
        snapshot['index_weights_percent'] = weights.get(symbol, {})
    if not snapshots:
        raise ValueError('DPS workbook has no validated capitalization rows')
    return snapshots, issues


def import_capitalization(db, client, day):
    url = f'https://dps.psx.com.pk/download/indhist/{day}.xls'
    response = client.get(url)
    response.raise_for_status()
    snapshots, issues = parse_constituents(response.content)
    lock_ingestion_writes(db, 'market-price-write')
    stamp = datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo('Asia/Karachi'))
    artifact = store_artifact(db, _source(db,'dps'), response.content, url=url, method='GET',
        parser_version='dps-capitalization-v1', content_type='application/vnd.ms-excel', effective_at=stamp)
    instruments = {i.symbol:i for i in db.scalars(select(Instrument).where(Instrument.symbol.in_(snapshots)))}
    existing = {o.instrument_id:o for o in db.scalars(select(MarketObservation).where(
        MarketObservation.artifact_id==artifact.id, MarketObservation.frequency=='capitalization'))}
    written, unmatched = 0, []
    for symbol, values in snapshots.items():
        instrument = instruments.get(symbol)
        if instrument is None:
            unmatched.append(symbol)
            continue
        values = {**values,'trade_date':str(day)}
        if instrument.id not in existing:
            db.add(MarketObservation(instrument_id=instrument.id, effective_at=stamp,
                frequency='capitalization', values_json=json.dumps(values,sort_keys=True), unit='PKR_and_shares',
                currency='PKR', artifact_id=artifact.id, adjustment_state='published_capitalization'))
            written += 1
    db.flush()
    # Canonical selection is scoped to this snapshot date, never the whole corpus.
    reconcile_market_observations(db, effective_at=stamp)
    for issue in issues:
        if not db.scalar(select(DataQualityIssue.id).where(DataQualityIssue.artifact_id==artifact.id,
            DataQualityIssue.rule=='invalid_dps_capitalization',DataQualityIssue.details_json==json.dumps(issue,sort_keys=True))):
            db.add(DataQualityIssue(artifact_id=artifact.id,rule='invalid_dps_capitalization',
                severity='warning',details_json=json.dumps(issue,sort_keys=True),selection_status='rejected'))
    return {'date':str(day),'validated':len(snapshots),'matched':len(snapshots)-len(unmatched),
        'written':written,'rejected':issues,'unmatched_symbols':unmatched,'artifact_id':artifact.id}


def capitalization(db, instrument_id, as_of=None):
    query = select(MarketObservation,SourceArtifact).join(SourceArtifact,
        SourceArtifact.id==MarketObservation.artifact_id).where(MarketObservation.instrument_id==instrument_id,
        MarketObservation.frequency=='capitalization',MarketObservation.is_selected.is_(True))
    if as_of:
        from datetime import timedelta
        query=query.where(MarketObservation.effective_at < datetime.combine(as_of+timedelta(days=1),
            datetime.min.time(),tzinfo=ZoneInfo('Asia/Karachi')))
    row=db.execute(query.order_by(MarketObservation.effective_at.desc()).limit(1)).first()
    if row is None:return None
    observation,artifact=row
    return {**json.loads(observation.values_json),'artifact_id':artifact.id,
        'artifact_sha256':artifact.sha256,'source_url':artifact.source_url,'observed_at':artifact.retrieved_at}


def capitalization_for_date(db, day):
    """One batch lookup for market tables, not one extra query per company."""
    from datetime import timedelta
    start = datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo('Asia/Karachi'))
    rows = db.execute(select(MarketObservation, SourceArtifact).join(SourceArtifact,
        SourceArtifact.id == MarketObservation.artifact_id).where(
        MarketObservation.frequency == 'capitalization', MarketObservation.is_selected.is_(True),
        MarketObservation.effective_at >= start, MarketObservation.effective_at < start + timedelta(days=1)))
    return {observation.instrument_id: {**json.loads(observation.values_json),
        'artifact_id': artifact.id, 'artifact_sha256': artifact.sha256,
        'source_url': artifact.source_url, 'observed_at': artifact.retrieved_at}
        for observation, artifact in rows}
