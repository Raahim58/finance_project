from datetime import date
import pytest
from sqlalchemy import select,func
from app.db.session import SessionLocal
from app.models.user import User
from app.models.workstation import Instrument
from app.models.document import DocumentEvidenceTag, DocumentChunk
from app.schemas.rag import RagSearchRequest
from app.services.rag_service import create_document_from_pages,ParsedPage,search_rag
from app.services.news_retrieval import tag_document
from app.tools.research_tools import ResearchInput,_search
from app.tools.registry import expand_model_data


def search(db,user,payload):
    result=_search(db,user,payload)
    result['data']=expand_model_data(result['data'])
    return result


def seed(db):
    user=User(email='retrieval@example.com',password_hash='unused');db.add(user)
    db.add(Instrument(symbol='LUCK',name='Lucky Cement Limited',sector='CEMENT'));db.flush()
    company=create_document_from_pages(db,[ParsedPage(1,'LUCK cement costs and demand financial report. '*12)],
        title='LUCK financial report',document_type='annual_report',symbol='LUCK',sector='Cement',
        published_date=date(2026,9,1),source_url='https://example.com/luck')
    sector=create_document_from_pages(db,[ParsedPage(1,'Cement demand and costs are affected by energy prices. '*12)],
        title='Cement demand and energy costs',document_type='news',published_date=date(2026,9,2),source_url='https://example.com/cement')
    broader=create_document_from_pages(db,[ParsedPage(1,'Sanctions and tariffs disrupt shipping and fuel supply. '*12)],
        title='Sanctions threaten shipping',document_type='news',published_date=date(2026,9,3),source_url='https://example.com/sanctions')
    return user,company,sector,broader


def test_company_sector_and_broader_without_fabricated_company_links():
    with SessionLocal() as db:
        user,company,sector,broader=seed(db)
        result=search(db,user,ResearchInput(query='LUCK cement costs sanctions',symbols=['LUCK'],topics=['geopolitics']))
        rows=result['data']['chunks']
        assert {r['document_id'] for r in rows}>={company.id,sector.id,broader.id}
        assert sector.symbol is None and broader.symbol is None
        assert {'company','sector','broader'}<={r['group'] for r in rows}
        assert all(r['source_ref'] and r['published_date'] for r in rows)
        assert 'audit' not in result['data']


def test_exact_company_mode_preserves_existing_rag_contract():
    with SessionLocal() as db:
        user,company,sector,_=seed(db)
        response=search_rag(db,user,RagSearchRequest(query='LUCK cement costs',symbols=['LUCK']))
        assert {c.document_id for c in response.chunks}=={company.id}
        result=search(db,user,ResearchInput(query='LUCK cement costs',symbols=['LUCK'],include_broader_context=False))
        assert {r['document_id'] for r in result['data']['chunks']}=={company.id}


def test_tags_are_idempotent_and_original_embeddings_are_unchanged():
    with SessionLocal() as db:
        _,_,sector,_=seed(db)
        before=db.scalar(select(func.count()).select_from(DocumentEvidenceTag))
        embeddings=list(db.execute(select(DocumentChunk.id, DocumentChunk.embedding_json)))
        tag_document(db,sector,'Cement demand and costs are affected by energy prices. '*12)
        assert db.scalar(select(func.count()).select_from(DocumentEvidenceTag))==before
        assert list(db.execute(select(DocumentChunk.id, DocumentChunk.embedding_json)))==embeddings


def test_dates_ownership_and_cursor_scope():
    with SessionLocal() as db:
        user,_,_,_=seed(db)
        other=User(email='other@example.com',password_hash='unused');db.add(other);db.flush()
        hidden=create_document_from_pages(db,[ParsedPage(1,'Cement costs sanctions demand. '*12)],
            title='Private cement costs',document_type='news',owner_user_id=other.id,visibility='private',
            published_date=date(2026,9,4),source_url='https://example.com/private')
        for i in range(5):
            create_document_from_pages(db,[ParsedPage(1,f'Cement costs sanctions demand market article {i}. '*10)],
                title=f'Cement costs {i}',document_type='news',published_date=date(2026,9,4),source_url=f'https://example.com/{i}')
        params=dict(query='LUCK cement costs sanctions',symbols=['LUCK'],topics=['geopolitics'],limit=3,date_from=date(2026,9,2))
        first=search(db,user,ResearchInput(**params))
        assert hidden.id not in {r['document_id'] for r in first['data']['chunks']}
        cursor=first['data']['coverage']['next_cursor'];assert cursor
        second=search(db,user,ResearchInput(**params,cursor=cursor))
        assert not {r['id'] for r in first['data']['chunks']} & {r['id'] for r in second['data']['chunks']}
        with pytest.raises(ValueError,match='cursor'):
            _search(db,other,ResearchInput(**params,cursor=cursor))


def test_provider_passages_are_deduplicated_but_saved_citations_keep_quotes():
    from app.ai.tool_loop import ToolExecution,_result_blocks
    from app.ai.providers.base import ContentBlock
    with SessionLocal() as db:
        user,_,_,_=seed(db)
        envelope=_search(db,user,ResearchInput(query='LUCK cement costs sanctions',symbols=['LUCK'],topics=['geopolitics']))
        checkpoint={'evidence':{},'next_evidence':1,'tool_trace':[]}
        first=_result_blocks(checkpoint,ToolExecution(ContentBlock('tool_call',id='call-1',name='research.search'),envelope,1.0))[0].result
        assert all('quote_snippet' not in source for source in first['sources'])
        assert all(item['source']['quote_snippet'] for item in checkpoint['evidence'].values())
        second=_result_blocks(checkpoint,ToolExecution(ContentBlock('tool_call',id='call-2',name='research.search'),envelope,1.0))[0].result
        assert all(not c.get('text') and c['previously_supplied'] for c in expand_model_data(second['data'])['chunks'])
