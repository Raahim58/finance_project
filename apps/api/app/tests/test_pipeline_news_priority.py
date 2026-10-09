from datetime import UTC,datetime,timedelta
from app.db.session import SessionLocal
from app.services.pipeline import runs

def test_news_and_commentary_dispatch_before_old_report_backlog():
    with SessionLocal() as db:
        for i in range(25):runs.enqueue(db,'report_fetch',f'old:{i}',{'report':{'posting_date':'2020-01-01'}},mode='historical')
        article=runs.enqueue(db,'fetch','news:1',{'candidate_id':'one'})
        commentary=runs.enqueue(db,'briefing','commentary:1',{})
        db.commit();sent=[]
        runs.dispatch(db,lambda *args:sent.append(args),limit=10)
        assert {r[0] for r in sent}=={article.id,commentary.id}
        assert all(stage!='report_fetch' for _,stage,_ in sent)

def test_old_report_children_inherit_explicit_historical_mode():
    with SessionLocal() as db:
        parent=runs.enqueue(db,'reports','catalog',{'symbol':'TEST'});db.commit()
        token=runs.claim(db,parent.id)
        runs.finish(db,parent.id,token,{},children=[('report_fetch','pdf:1',{'report':{}},'historical')])
        from sqlalchemy import select
        from app.models.pipeline import IngestionStageRun
        child=db.scalar(select(IngestionStageRun).where(IngestionStageRun.stage=='report_fetch'))
        assert child.mode=='historical'

def test_outside_scope_news_does_not_block_reports():
    with SessionLocal() as db:
        runs.enqueue(db,'fetch','outside:news',{'candidate_id':'one'})
        report=runs.enqueue(db,'report_fetch','canary:report',{'report':{}},mode='historical')
        db.commit();sent=[]
        runs.dispatch(db,lambda *args:sent.append(args),scope='canary')
        assert [r[0] for r in sent]==[report.id]

def test_unstaffed_enrichment_does_not_block_reports():
    with SessionLocal() as db:
        runs.enqueue(db,'enrich','optional:model',{})
        runs.enqueue(db,'report_fetch','archive:report',{'report':{}},mode='historical')
        db.commit();sent=[]
        runs.dispatch(db,lambda *args:sent.append(args))
        assert any(stage=='report_fetch' for _,stage,_ in sent)


def test_downloaded_report_processing_gets_slots_during_news_backlog():
    with SessionLocal() as db:
        for i in range(25):
            runs.enqueue(db, 'fetch', f'news:{i}', {'candidate_id': str(i)})
        downloaded = runs.enqueue(db, 'report_extract', 'downloaded', {'document_id': 'fixture'}, mode='historical')
        runs.enqueue(db, 'report_fetch', 'new-download', {'report': {}}, mode='historical')
        db.commit(); sent = []
        runs.dispatch(db, lambda *args: sent.append(args), limit=10)
        assert any(identifier == downloaded.id for identifier, _, _ in sent)
        assert any(stage == 'fetch' for _, stage, _ in sent)
        assert not any(stage == 'report_fetch' for _, stage, _ in sent)


def test_report_extraction_precedes_older_downloads_and_catalogs():
    with SessionLocal() as db:
        for i in range(25):
            runs.enqueue(db, 'report_fetch', f'old-download:{i}', {'report': {}}, mode='historical')
        downloaded = runs.enqueue(db, 'report_extract', 'downloaded', {'document_id': 'fixture'}, mode='historical')
        db.commit(); sent = []
        runs.dispatch(db, lambda *args: sent.append(args), limit=10)
        assert sent[0][0] == downloaded.id
