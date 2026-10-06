"""Read-only stage/source coverage and capacity report."""
import json
from sqlalchemy import func,select,text
from app.db.session import SessionLocal
from app.models.pipeline import IngestionStageRun,SourceTarget,CompanyIntelligenceSection
from app.services.pipeline.retention import capacity


def status(db):
    return {'stages':[{'stage':s,'mode':m,'status':st,'count':c} for s,m,st,c in db.execute(
        select(IngestionStageRun.stage,IngestionStageRun.mode,IngestionStageRun.status,func.count())
        .group_by(IngestionStageRun.stage,IngestionStageRun.mode,IngestionStageRun.status))],
        'targets':[{'id':r.id,'adapter':r.adapter_key,'scope':r.scope_key,'enabled':r.enabled,'schedule':r.schedule,'cursor':r.cursor}
            for r in db.scalars(select(SourceTarget))],
        'prepared_sections':db.scalar(select(func.count()).select_from(CompanyIntelligenceSection).where(CompanyIntelligenceSection.is_selected.is_(True))),
        'capacity':capacity(db)}


def main():
    with SessionLocal() as db:
        if db.bind.dialect.name=='postgresql': db.execute(text('SET TRANSACTION READ ONLY'))
        print(json.dumps(status(db),default=str));db.rollback()

if __name__=='__main__':main()
