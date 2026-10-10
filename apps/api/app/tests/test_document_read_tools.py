"""Offline document read tools contracts and fixtures."""

from datetime import UTC, datetime
from decimal import Decimal
from pypdf import PdfWriter
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.user import User
from app.models.workstation import Event, EventEntityLink, EventSource, Instrument
from app.services.rag_service import ParsedPage, create_document_from_pages
from app.tools import build_tool_registry
from app.tools.registry import expand_model_data
from app.tests.support.tools import _seed, base64_decode
import pytest


@pytest.mark.usefixtures("database")
def test_research_events_period_pagination_returns_citable_sources(monkeypatch):
    _, user_id = _seed(monkeypatch)
    with SessionLocal.begin() as db:
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        for index, day in enumerate((10, 11)):
            event = Event(
                event_type="news",
                title=f"Observed MEBL event {index}",
                occurred_at=datetime(2026, 8, day, 12, tzinfo=UTC),
                cluster_key=f"phase8-event-{index}",
                materiality="medium",
                direction="neutral",
                confidence=Decimal("0.9"),
            )
            db.add(event)
            db.flush()
            db.add(
                EventEntityLink(
                    event_id=event.id,
                    entity_type="instrument",
                    entity_key=instrument.symbol,
                    link_method="test_fixture",
                    confidence=Decimal("1"),
                )
            )
            db.add(
                EventSource(
                    event_id=event.id,
                    source_name="Issuer notice",
                    source_url=f"https://example.com/mebl-{index}",
                    published_at=event.occurred_at,
                )
            )
    with SessionLocal() as db:
        user = db.get(User, user_id)
        registry = build_tool_registry()
        first = registry.invoke(
            "research.events",
            db,
            user,
            {
                "entity_key": "MEBL",
                "period_start": "2026-08-10",
                "period_end": "2026-08-11",
                "limit": 1,
            },
        )
        assert first["coverage"]["returned"] == 1
        assert first["coverage"]["remaining"] is None
        assert first["coverage"]["continuation"] == "1"
        event = expand_model_data(first["data"])["events"][0]
        assert event["source_refs"] == [first["sources"][0]["id"]]
        assert "sources" not in event
        assert first["sources"][0]["source_url"].startswith("https://example.com/")


@pytest.mark.usefixtures("database")
def test_document_discovery_reads_full_pages_enforces_ownership_and_handles_gaps(monkeypatch):
    _, owner_id = _seed(monkeypatch)
    with SessionLocal.begin() as db:
        owner = db.get(User, owner_id)
        other = User(email="other@example.com", password_hash="not-used")
        db.add(other)
        db.flush()
        document = create_document_from_pages(
            db,
            [
                ParsedPage(
                    1,
                    "Revenue table\nRevenue PKR 100 million"
                    + " Full evidence preserved." * 40
                    + "\nQualification: unaudited.",
                ),
                ParsedPage(2, "Adjacent note\nThe amount excludes discontinued operations."),
                ParsedPage(4, "Later page after an extraction gap."),
            ],
            title="MEBL observed interim report",
            document_type="quarterly_report",
            symbol="MEBL",
            source_name="Issuer filing",
            source_url="https://example.test/mebl-report.pdf",
            owner_user_id=owner.id,
            visibility="private",
            commit=False,
        )
        document_id = document.id
        other_id = other.id
    with SessionLocal() as db:
        owner = db.get(User, owner_id)
        registry = build_tool_registry()
        discovery = registry.invoke(
            "documents.discover", db, owner, {"query": "revenue qualification"}
        )
        discovery_data = expand_model_data(discovery["data"])
        assert discovery["coverage"]["returned"] == 1
        assert discovery_data["documents"][0]["document_id"] == document_id
        assert all(len(source["quote_snippet"] or "") <= 320 for source in discovery["sources"])
        assert all(
            len(match["snippet"]) <= 320 for match in discovery_data["documents"][0]["matches"]
        )
        assert any(
            match["excerpt_truncated"] for match in discovery_data["documents"][0]["matches"]
        )
        chunk_id = discovery_data["documents"][0]["matches"][0]["chunk_id"]
        chunk_read = registry.invoke(
            "documents.read",
            db,
            owner,
            {"document_id": document_id, "mode": "chunks", "chunk_ids": [chunk_id]},
        )
        chunk_data = expand_model_data(chunk_read["data"])
        assert chunk_data["chunks"][0]["chunk_id"] == chunk_id
        assert "Qualification: unaudited." in chunk_data["chunks"][0]["text"]
        assert len(chunk_data["chunks"][0]["text"]) > 320
        assert {source["chunk_id"] for source in chunk_read["sources"]} == {chunk_id}
        first = registry.invoke(
            "documents.read",
            db,
            owner,
            {"document_id": document_id, "mode": "pages", "page_start": 1, "page_end": 4},
        )
        duplicate = registry.invoke(
            "documents.read",
            db,
            owner,
            {"document_id": document_id, "mode": "pages", "page_start": 1, "page_end": 4},
        )
        first_data = expand_model_data(first["data"])
        assert first["data"] == duplicate["data"]
        assert [row["page_number"] for row in first_data["pages"]] == [1, 2, 4]
        assert first_data["pages"][0]["text"].endswith("Qualification: unaudited.")
        assert first_data["extraction_gaps"] == [3]
        assert (
            registry.invoke(
                "documents.page_images",
                db,
                owner,
                {"document_id": document_id, "page_start": 1, "page_end": 1},
            )["data"]["error"]["code"]
            == "original_unavailable"
        )
        other = db.get(User, other_id)
        assert (
            registry.invoke(
                "documents.read",
                db,
                other,
                {"document_id": document_id, "mode": "pages", "page_start": 1, "page_end": 1},
            )["data"]["error"]["code"]
            == "document_not_found"
        )


@pytest.mark.usefixtures("database")
def test_navigation_and_page_images_use_retained_pdf(monkeypatch, tmp_path):
    _, owner_id = _seed(monkeypatch)
    pdf_path = tmp_path / "retained.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    writer.add_outline_item("Risk notes", 1)
    with pdf_path.open("wb") as stream:
        writer.write(stream)
    with SessionLocal.begin() as db:
        owner = db.get(User, owner_id)
        document = create_document_from_pages(
            db,
            [ParsedPage(1, "Cover"), ParsedPage(2, "Risk notes")],
            title="Retained original",
            document_type="annual_report",
            symbol="MEBL",
            source_name="Issuer filing",
            source_url="https://example.test/retained.pdf",
            local_file_path=str(pdf_path),
            owner_user_id=owner.id,
            visibility="private",
            commit=False,
        )
        document_id = document.id
    with SessionLocal() as db:
        owner = db.get(User, owner_id)
        registry = build_tool_registry()
        navigation = registry.invoke("documents.navigate", db, owner, {"document_id": document_id})
        navigation_data = expand_model_data(navigation["data"])
        assert navigation_data["bookmarks"] == [
            {"title": "Risk notes", "page_number": 2, "precision": "page_navigation"}
        ]
        assert (
            navigation_data["bookmark_precision"] == "page_navigation_not_exact_section_boundaries"
        )
        images = registry.invoke(
            "documents.page_images",
            db,
            owner,
            {"document_id": document_id, "page_start": 2, "page_end": 2},
        )
        assert images["status"] == "ok"
        image_data = expand_model_data(images["data"])
        assert base64_decode(image_data["images"][0]["base64"]).startswith(b"\x89PNG")


def test_event_pagination_applies_offset_once(monkeypatch):
    from app.tools.research_tools import EventInput, _events

    # A database-like reader applies offset before returning limit+1 rows.
    events = [{"id": str(index), "sources": []} for index in range(7)]

    def reader(_db, **kwargs):
        offset = kwargs.get("offset", 0)
        return events[offset : offset + kwargs["limit"]]

    # Use the actual event service signature adapter below.
    import app.tools.research_tools as research

    monkeypatch.setattr(research, "list_events", lambda _db, **kwargs: reader(_db, **kwargs))
    seen, cursor = [], None
    for _ in range(4):
        result = expand_model_data(_events(None, None, EventInput(cursor=cursor, limit=2)))
        seen.extend(row["id"] for row in result["data"]["events"])
        cursor = result["coverage"]["continuation"]
        if cursor is None:
            break
    assert seen == [str(index) for index in range(7)]
    assert cursor is None
