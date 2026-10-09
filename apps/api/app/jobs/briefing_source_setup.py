"""Add approved original-news discovery and morning commentary to the pipeline."""
import json
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.pipeline import SourceTarget
from app.services.evidence_pipeline import ensure_source_config
from app.services.ingestion_persistence import source
from app.core.config import settings


def configure(db, *, batch=None, news_limit=6):
    if settings.pipeline_dispatch_scope and not batch:
        raise ValueError('Existing canary batch is required; refusing unscoped activation')
    publisher,config,_=ensure_source_config(db,'briefing_news');publisher.enabled=True
    research=source(db,'Public morning research feed','commentary','https://stock-market-analysis-7l5.pages.dev',50,1440,
        'Extra sector/company interpretation; original article publishers supply news evidence.')
    research.enabled=True
    targets=[]
    for data_source,scope,adapter,schedule,configid in ((publisher,'briefing:original_news','briefing_news','news',config.id),
            (research,'briefing:morning_analysis','briefing','briefing',None)):
        target=db.scalar(select(SourceTarget).where(SourceTarget.data_source_id==data_source.id,SourceTarget.scope_key==scope))
        if not target:
            target=SourceTarget(data_source_id=data_source.id,evidence_config_id=configid,scope_key=scope,adapter_key=adapter,schedule=schedule,enabled=True,cursor={})
            db.add(target)
        target.enabled=True
        target.cursor={**target.cursor,**({'canary_batch':batch} if batch else {}),**({'news_limit':news_limit} if adapter=='briefing_news' else {})}
        targets.append(target)
    db.commit();return {'targets':[t.id for t in targets],'original_article_limit_per_slot':news_limit,'analysis_classification':'interpretation'}


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--news-limit',type=int,default=6,choices=range(1,51))
    args=parser.parse_args()
    with SessionLocal() as db:
        existing=db.scalar(select(SourceTarget).where(SourceTarget.enabled.is_(True),SourceTarget.scope_key.like('canary:%')))
        print(json.dumps(configure(db,batch=existing.cursor.get('canary_batch') if existing else None,news_limit=args.news_limit)))

if __name__=='__main__':main()
