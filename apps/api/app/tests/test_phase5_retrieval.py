from datetime import date

from sqlalchemy import select

from app.db.session import SessionLocal
from app.domain.retrieval import (
    build_retrieval_plan,
    canonical_document_type,
    classify_chunk_content,
    reciprocal_rank_fusion,
)
from app.models.document import Document, DocumentChunk
from app.services.market_ingestion import generate_mock_market_data
from app.services.rag_service import ParsedPage, chunk_page_text, create_document_from_pages


def _auth_headers(client):
    response = client.post(
        "/auth/signup",
        json={"email": "phase5@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _seed_companies():
    with SessionLocal() as db:
        generate_mock_market_data(db, days=2, end_date=date(2026, 6, 30))


def _public_document(
    *,
    title: str,
    text: str,
    symbol: str | None,
    document_type: str,
    published_date: date,
    source_name: str = "Pakistan Stock Exchange",
    source_url: str | None = None,
):
    with SessionLocal() as db:
        return create_document_from_pages(
            db,
            [ParsedPage(page_number=1, text=text)],
            title=title,
            document_type=document_type,
            symbol=symbol,
            source_name=source_name,
            source_url=(
                f"https://example.test/{title.casefold().replace(' ', '-')}"
                if source_url is None
                else source_url
            ),
            published_date=published_date,
            visibility="public",
        ).id


def test_standard_rrf_uses_rank_positions():
    scores = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60)
    assert scores["b"] == (1 / 62) + (1 / 61)
    assert scores["a"] == 1 / 61
    assert scores["c"] == 1 / 62
    assert scores["b"] > scores["a"] > scores["c"]


def test_document_type_aliases_and_time_horizon_are_deterministic():
    assert canonical_document_type("Announcements") == "announcement"
    plan = build_retrieval_plan(
        query="issuer notice",
        symbols=["mebl"],
        sectors=None,
        document_types=["PSX Notice"],
        date_from=None,
        date_to=None,
        time_horizon="quarter",
        portfolio_id=None,
        limit=5,
        today=date(2026, 8, 24),
    )
    assert plan.symbols == ("MEBL",)
    assert plan.document_types == ("announcement",)
    assert plan.date_from == date(2026, 5, 26)
    assert plan.date_to == date(2026, 8, 24)


def test_structure_aware_chunking_keeps_heading_with_body():
    text = (
        "RISK MANAGEMENT\n\n"
        "Management monitors liquidity, credit quality, and deposit concentration.\n\n"
        "OUTLOOK\n\n"
        "The bank expects cautious lending while preserving capital buffers."
    )
    chunks = chunk_page_text(text, 4)
    assert chunks == [(text, 4)]
    assert "RISK MANAGEMENT\n\nManagement" in chunks[0][0]
    assert "OUTLOOK\n\nThe bank" in chunks[0][0]


def test_table_and_boilerplate_content_are_classified():
    assert classify_chunk_content("Revenue 100 200 300 400 500 600") == "table"
    assert classify_chunk_content("TABLE OF CONTENTS\nCorporate profile\nGovernance") == "boilerplate"
    assert classify_chunk_content("Management discussed demand and margins.") == "narrative"


def test_explicit_entity_and_announcement_filters_are_hard(client):
    _seed_companies()
    headers = _auth_headers(client)
    mebl_id = _public_document(
        title="MEBL Capital Announcement",
        text="Meezan Bank announced a capital update and deposit strategy.",
        symbol="MEBL",
        document_type="Announcements",
        published_date=date(2026, 8, 20),
    )
    _public_document(
        title="NBP Capital News",
        text="National Bank reported a capital update and deposit strategy.",
        symbol="NBP",
        document_type="news",
        published_date=date(2026, 8, 21),
    )

    response = client.post(
        "/rag/search",
        headers=headers,
        json={
            "query": "capital update deposit strategy",
            "symbols": ["MEBL"],
            "document_types": ["Announcements"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert {row["document_id"] for row in body["chunks"]} == {mebl_id}
    assert {row["document_type"] for row in body["chunks"]} == {"announcement"}
    assert body["audit"]["plan"]["document_types"] == ["announcement"]


def test_weak_results_and_uncitable_results_are_not_padded(client):
    _seed_companies()
    headers = _auth_headers(client)
    _public_document(
        title="Uncitable Bank Note",
        text="Deposit growth remained resilient and capital buffers were stable.",
        symbol="MEBL",
        document_type="annual_report",
        published_date=date(2026, 8, 20),
        source_name="Unknown",
        source_url="",
    )
    response = client.post(
        "/rag/search",
        headers=headers,
        json={"query": "deposit growth capital buffers", "symbols": ["MEBL"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["chunks"] == []
    assert body["audit"]["rejected_by_reason"]["missing_citation_provenance"] >= 1


def test_synthetic_documents_are_excluded_and_audit_is_returned(client):
    _seed_companies()
    headers = _auth_headers(client)
    with SessionLocal() as db:
        create_document_from_pages(
            db,
            [ParsedPage(1, "Synthetic uniquealpha evidence about deposits.")],
            title="Synthetic MEBL facts",
            document_type="synthetic_demo_facts",
            symbol="MEBL",
            source_name="Deterministic Demo Seed",
            source_url="demo://company/MEBL/2025",
            published_date=date(2026, 3, 1),
            visibility="public",
        )
    response = client.post(
        "/rag/search",
        headers=headers,
        json={"query": "uniquealpha deposits", "symbols": ["MEBL"]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert response.json()["audit"]["embedding_model"] == "token-hash-v1-test-only"


def test_source_tier_and_chunk_metadata_are_persisted():
    _seed_companies()
    document_id = _public_document(
        title="Official Result",
        text="RESULTS\n\nThe issuer reported improving operating margins.",
        symbol="MEBL",
        document_type="annual_report",
        published_date=date(2026, 8, 20),
    )
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        chunk = db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == document_id))
        assert document is not None and document.source_tier == 1
        assert document.data_status == "observed"
        assert chunk is not None and chunk.content_type == "narrative"
        assert chunk.embedding_index_version == 2
        assert chunk.embedding_status == "indexed"
