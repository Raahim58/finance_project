"""Activate full-universe quote/EOD targets and retire queued quote canaries."""
import json
from sqlalchemy import select
from app.db.session import SessionLocal
from app.jobs.pipeline_bootstrap import bootstrap
from app.models.pipeline import IngestionStageRun, SourceTarget
from app.models.workstation import DataSource


def activate(db):
    bootstrap(db)
    enabled = []; disabled = []; retired = 0
    for target in db.scalars(select(SourceTarget).where(SourceTarget.adapter_key.in_(('prices','market_daily')))):
        if target.scope_key not in ('prices', 'market_daily') or target.cursor.get('canary_batch'):
            target.enabled = False; disabled.append(target.id); continue
        target.enabled = True
        cursor = dict(target.cursor)
        cursor.pop('symbols', None); cursor.pop('canary_batch', None)
        target.cursor = cursor
        db.get(DataSource, target.data_source_id).enabled = True
        enabled.append(target.adapter_key)
    for row in db.scalars(select(IngestionStageRun).where(IngestionStageRun.stage == 'prices',
        IngestionStageRun.status.in_(('queued','retry_wait')))):
        if row.input.get('canary_batch') or row.subject_key.startswith('canary:'):
            row.status = 'superseded'; row.error_code = 'retired_price_canary'
            row.dispatch_until = None; retired += 1
    db.commit()
    return {'full_market_targets': enabled, 'disabled_price_canaries': len(disabled), 'retired_queued_canaries': retired}


if __name__ == '__main__':
    with SessionLocal() as db: print(json.dumps(activate(db)))
