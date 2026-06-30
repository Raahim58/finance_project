from datetime import date

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.document import Citation, DocumentChunk, DocumentPage
from app.services.market_ingestion import generate_mock_market_data


def _auth_headers(client):
    response = client.post(
        "/auth/signup",
        json={"email": "rag@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _seed_companies():
    with SessionLocal() as db:
        generate_mock_market_data(db, days=2, end_date=date(2026, 6, 30))


def test_ingest_text_document_and_search_returns_citations(client):
    _seed_companies()
    headers = _auth_headers(client)
    text = (
        "Meezan Bank reported deposit growth and stable asset quality. "
        "Management commentary highlighted Islamic banking demand, cautious lending, "
        "and branch network expansion. Dividend policy remains dependent on capital buffers. "
    ) * 12

    ingest = client.post(
        "/documents/ingest-text",
        headers=headers,
        json={
            "title": "MEBL Annual Report Snippet",
            "document_type": "annual_report",
            "symbol": "MEBL",
            "fiscal_year": 2025,
            "source_name": "Demo annual report",
            "source_url": "https://example.com/mebl-annual",
            "published_date": "2026-03-15",
            "text": text,
        },
    )
    assert ingest.status_code == 201
    document = ingest.json()
    assert document["symbol"] == "MEBL"
    assert document["sector"] == "Banking"
    assert document["status"] == "parsed"

    with SessionLocal() as db:
        pages = db.scalars(select(DocumentPage)).all()
        chunks = db.scalars(select(DocumentChunk)).all()
        citations = db.scalars(select(Citation)).all()
    assert len(pages) == 1
    assert len(chunks) >= 1
    assert len(citations) == len(chunks)

    search = client.post(
        "/rag/search",
        json={
            "query": "Islamic banking deposit growth",
            "symbols": ["MEBL"],
            "document_types": ["annual_report"],
            "limit": 3,
        },
    )
    assert search.status_code == 200
    body = search.json()
    assert body["chunks"]
    assert body["citations"]
    assert body["scores"]
    assert body["chunks"][0]["symbol"] == "MEBL"
    assert body["chunks"][0]["citation"]["title"] == "MEBL Annual Report Snippet"
    assert body["chunks"][0]["citation"]["source_url"] == "https://example.com/mebl-annual"
    assert "deposit" in body["chunks"][0]["chunk_text"]


def test_rag_filters_and_empty_results(client):
    _seed_companies()
    headers = _auth_headers(client)
    response = client.post(
        "/documents/ingest-text",
        headers=headers,
        json={
            "title": "SYS Quarterly Snippet",
            "document_type": "quarterly_report",
            "symbol": "SYS",
            "sector": "Technology",
            "source_name": "Demo quarterly report",
            "text": "Systems Limited discussed export revenue, cloud services, and software delivery margins.",
        },
    )
    assert response.status_code == 201

    no_symbol_match = client.post(
        "/rag/search",
        json={"query": "cloud services", "symbols": ["MEBL"], "limit": 5},
    )
    assert no_symbol_match.status_code == 200
    assert no_symbol_match.json()["chunks"] == []

    no_content_match = client.post(
        "/rag/search",
        json={"query": "cement clinker dispatches", "symbols": ["SYS"], "limit": 5},
    )
    assert no_content_match.status_code == 200
    assert no_content_match.json()["chunks"] == []


def test_document_list_and_detail(client):
    _seed_companies()
    headers = _auth_headers(client)
    created = client.post(
        "/documents/ingest-text",
        headers=headers,
        json={
            "title": "FFC Investor Note",
            "document_type": "investor_presentation",
            "symbol": "FFC",
            "source_name": "Demo presentation",
            "text": "Fauji Fertilizer commentary covered urea pricing and gas cost sensitivity.",
        },
    )
    assert created.status_code == 201
    document_id = created.json()["id"]

    docs = client.get("/documents?symbol=FFC")
    assert docs.status_code == 200
    assert docs.json()[0]["id"] == document_id

    detail = client.get(f"/documents/{document_id}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "FFC Investor Note"
