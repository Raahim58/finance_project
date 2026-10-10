from datetime import date
from decimal import Decimal
import json
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.workstation import FinancialFact, Instrument
from app.providers.fundamentals.extraction import FinancialPage, extract_facts
from app.services.financial_extraction_replay import save_extracted_facts
import pytest

pytestmark = pytest.mark.usefixtures("database")


def test_reextract_preserves_original_amount_and_promotes_normalized_replacement():
    with SessionLocal() as db:
        instrument=Instrument(id='issuer',symbol='TEST',name='Test')
        document=Document(id='report',title='Test report',document_type='annual_report',source_name='Test',content_hash='pinned')
        db.add_all([instrument,document]);db.flush()
        old=FinancialFact(id='old',instrument_id=instrument.id,document_id=document.id,taxonomy_key='assets',
            period_type='annual',period_end=date(2025,12,31),value=Decimal(3000),unit='PKR',currency='PKR',
            confidence=Decimal('.9'),consolidated=True,version=1)
        db.add(old);db.flush()
        facts,diagnostics=extract_facts([FinancialPage(1,"Rupees ('000)\nTotal assets 3,000")],date(2025,12,31))
        new=save_extracted_facts(db,document,instrument,facts,diagnostics,'v5',strict=True)
        assert old.value==Decimal(3000) and old.confidence==0
        assert json.loads(old.diagnostics_json)['reextraction']['original_confidence']=='0.9'
        assert new[0].value==Decimal(3_000_000) and new[0].version==2
        assert new[0].page_number==1 and new[0].period_type=='instant'


def test_unavailable_units_never_keep_old_unverified_amounts_active():
    with SessionLocal() as db:
        instrument=Instrument(id='issuer',symbol='TEST',name='Test')
        document=Document(id='report',title='Test',document_type='annual_report',source_name='Test',content_hash='pinned')
        db.add_all([instrument,document]);db.flush()
        old=FinancialFact(instrument_id=instrument.id,document_id=document.id,taxonomy_key='assets',period_type='annual',
            period_end=date(2025,12,31),value=100,unit='PKR',confidence=Decimal('.9'),consolidated=True)
        db.add(old);db.flush()
        assert save_extracted_facts(db,document,instrument,[],['scale unknown'],'v5',strict=True)==[]
        assert old.confidence==0 and old.value==100


def test_task_replays_old_version_and_then_is_idempotent(monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from app.jobs import phase2_tasks
    from app.core.config import settings
    from app.models.workstation import DataSource, SourceArtifact, IngestionCoverage
    from app.providers.fundamentals.extraction import FINANCIAL_EXTRACTION_VERSION
    content=b'offline source fixture'
    monkeypatch.setattr(settings,'pipeline_enabled',True)
    monkeypatch.setattr(phase2_tasks,'get_artifact_store',lambda _:SimpleNamespace(get=lambda _:content))
    monkeypatch.setattr(phase2_tasks,'parse_financial_pdf',lambda _:([FinancialPage(1,"Consolidated\nStatement of financial position\nDecember 31, 2025\nPKR millions\nTotal assets 2")],'text_native',[]))
    with SessionLocal() as db:
        issuer=Instrument(id='issuer',symbol='TEST',name='Test')
        source=DataSource(id='source',name='Offline fixture',source_type='report')
        db.add_all([issuer,source]);db.flush()
        artifact=SourceArtifact(id='artifact',data_source_id=source.id,sha256=hashlib.sha256(content).hexdigest(),storage_path='fixture',parser_version='fixture',source_url='https://example.test/offline-report.pdf')
        db.add(artifact);db.flush()
        doc=Document(id='report',symbol='TEST',title='TEST Annual Report December 31, 2025',document_type='annual_report',source_name='Fixture',content_hash=artifact.sha256,artifact_id=artifact.id,extraction_version='old-version')
        db.add(doc);db.flush()
        db.add(IngestionCoverage(instrument_id=issuer.id,dataset_type='financial_extract',period_key=doc.id,source='psx_financials',status='complete',item_count=1))
        db.add(FinancialFact(id='old',instrument_id=issuer.id,document_id=doc.id,taxonomy_key='assets',period_type='annual',period_end=date(2025,12,31),value=2,unit='PKR',currency='PKR',confidence=Decimal('.9'),consolidated=True))
        db.commit()
    result=phase2_tasks.financial_extract('report')
    assert result['facts']==1
    with SessionLocal() as db:
        assert db.get(Document,'report').extraction_version==FINANCIAL_EXTRACTION_VERSION
        rows=list(db.scalars(select(FinancialFact).where(FinancialFact.document_id=='report')))
        assert len(rows)==2 and db.get(FinancialFact,'old').confidence==0
        assert next(row for row in rows if row.confidence>0).value==2_000_000
    assert phase2_tasks.financial_extract('report')['idempotent'] is True
