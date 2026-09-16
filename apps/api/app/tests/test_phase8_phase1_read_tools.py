"""Phase 8 Phase 1 evidence fidelity and read-only tool acceptance tests."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pypdf import PdfWriter
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.document import Document
from app.models.intelligence_context import ContextRefreshRequest
from app.models.market import MarketPrice
from app.models.portfolio import PortfolioTransaction
from app.models.user import User
from app.models.workstation import (
    AllocationSet,
    Event,
    EventEntityLink,
    EventSource,
    FinancialFact,
    Instrument,
)
from app.seed.demo import seed_workstation
from app.services.rag_service import ParsedPage, create_document_from_pages
from app.tools import build_tool_registry
from app.tools.registry import expand_model_data


def _seed(monkeypatch):
    monkeypatch.setenv("DEMO_USER_PASSWORD", "local-test-password")
    result = seed_workstation(include_mock_world=True)
    with SessionLocal() as db:
        return result, db.scalar(select(User).where(User.email == result["user_email"])).id


def _counts(db):
    return {
        "transactions": db.scalar(select(func.count()).select_from(PortfolioTransaction)),
        "allocations": db.scalar(select(func.count()).select_from(AllocationSet)),
        "documents": db.scalar(select(func.count()).select_from(Document)),
        "refreshes": db.scalar(select(func.count()).select_from(ContextRefreshRequest)),
    }


def test_catalog_is_generated_from_pydantic_and_refresh_is_not_allowlisted():
    registry = build_tool_registry()
    catalog = {item["name"]: item for item in registry.model_catalog()}
    assert "research.refresh_company" not in catalog
    assert {
        "research.company_sections",
        "market.universe",
        "allocation.verify",
        "documents.discover",
        "documents.read",
        "documents.navigate",
        "documents.page_images",
    } <= set(catalog)
    assert catalog["documents.discover"]["input_schema"] == next(
        item.input_model.model_json_schema()
        for item in registry.definitions()
        if item.name == "documents.discover"
    )
    with pytest.raises(KeyError, match="not allowlisted"):
        registry.invoke("research.refresh_company", None, None, {})


def test_errors_are_stable_and_do_not_expose_exception_text():
    result = build_tool_registry().invoke("documents.read", None, None, {"document_id": "x"})
    assert result["status"] == "invalid_arguments"
    assert result["data"] == {"error": {"code": "invalid_arguments", "fields": ["mode"]}}


def test_company_sections_preserve_period_unit_source_and_have_no_side_effects(monkeypatch):
    prohibited_calls = []

    def prohibited(*_args, **_kwargs):
        prohibited_calls.append(True)
        raise AssertionError("prohibited side effect")

    monkeypatch.setattr("app.services.ingestion_service.refresh_company_research", prohibited)
    monkeypatch.setattr("app.ai.providers.http_placeholders.AnthropicProvider.chat", prohibited)
    seeded, user_id = _seed(monkeypatch)
    with SessionLocal.begin() as db:
        user = db.get(User, user_id)
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        db.add_all(
            [
                FinancialFact(
                    instrument_id=instrument.id,
                    taxonomy_key="net_income",
                    period_type="annual",
                    period_end=date(2023, 12, 31),
                    value=Decimal("101.25"),
                    unit="million",
                    currency="PKR",
                    consolidated=True,
                    source_label="Issuer annual report",
                ),
                FinancialFact(
                    instrument_id=instrument.id,
                    taxonomy_key="net_income",
                    period_type="annual",
                    period_end=date(2023, 12, 31),
                    value=Decimal("99.75"),
                    unit="million",
                    currency="PKR",
                    consolidated=True,
                    source_label="Exchange filing",
                ),
            ]
        )
    with SessionLocal() as db:
        user = db.get(User, user_id)
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        before = _counts(db)
        result = build_tool_registry().invoke(
            "research.company_sections",
            db,
            user,
            {"instrument_id": instrument.id, "sections": ["company_facts"]},
        )
        assert result["status"] == "ok"
        data = expand_model_data(result["data"])
        facts = data["sections"][0]["data"]["fundamentals"]
        observed = {
            (row["period_end"], row["value"], row["unit"], row["source"])
            for row in facts
            if row["period_end"] == "2023-12-31"
        }
        assert observed == {
            ("2023-12-31", "101.25000000", "million", "Issuer annual report"),
            ("2023-12-31", "99.75000000", "million", "Exchange filing"),
        }
        assert {row["period_end"] for row in facts} >= {
            "2023-12-31",
            "2024-12-31",
            "2025-12-31",
        }
        assert data["measurements"][0]["size_kind"] == "estimate"
        assert set(result["data"]["sections"]) == {"columns", "rows"}
        assert _counts(db) == before
        assert prohibited_calls == []
        assert seeded["portfolio_id"]

        first_page = build_tool_registry().invoke(
            "research.company_sections",
            db,
            user,
            {
                "instrument_id": instrument.id,
                "sections": ["company_facts"],
                "period_start": "2023-01-01",
                "period_end": "2023-12-31",
                "limit": 1,
            },
        )
        first_data = expand_model_data(first_page["data"])
        assert first_page["coverage"]["returned"] == 1
        assert first_page["coverage"]["remaining"] == 1
        assert first_page["coverage"]["continuation"] == "1"
        assert first_data["sections"][0]["evidence_refs"]
        assert "evidence" not in first_data["sections"][0]
        assert len(first_page["sources"]) == 1

        second_page = build_tool_registry().invoke(
            "research.company_sections",
            db,
            user,
            {
                "instrument_id": instrument.id,
                "sections": ["company_facts"],
                "period_start": "2023-01-01",
                "period_end": "2023-12-31",
                "cursor": "1",
                "limit": 1,
            },
        )
        assert second_page["coverage"]["returned"] == 1
        assert second_page["coverage"]["remaining"] == 0
        assert second_page["coverage"]["continuation"] is None


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


def test_universe_pagination_is_stable_and_reports_coverage(monkeypatch):
    _, user_id = _seed(monkeypatch)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        registry = build_tool_registry()
        first = registry.invoke("market.universe", db, user, {"limit": 10})
        second = registry.invoke(
            "market.universe", db, user, {"limit": 10, "cursor": first["coverage"]["continuation"]}
        )
        assert first["coverage"]["returned"] == 10
        assert first["coverage"]["remaining"] == 27
        assert first["data"]["rows"][-1][1] < second["data"]["rows"][0][1]
        assert first["data"]["columns"][-2:] == ["sector", "classification_source"]


def test_allocation_verification_uses_stored_values_without_financial_writes(monkeypatch):
    seeded, user_id = _seed(monkeypatch)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        before = _counts(db)
        result = build_tool_registry().invoke(
            "allocation.verify",
            db,
            user,
            {
                "portfolio_id": seeded["portfolio_id"],
                "allowed_instrument_ids": [instrument.id],
                "proposal": {
                    "legs": [
                        {
                            "instrument_id": instrument.id,
                            "side": "buy",
                            "gross_amount": "1000",
                        }
                    ],
                    "rationale": "Test-only candidate",
                },
            },
        )
        assert result["status"] == "ok"
        data = expand_model_data(result["data"])
        assert data["financial_state_mutated"] is False
        assert data["legs"][0]["price"] == str(
            db.execute(
                select(MarketPrice.close)
                .where(MarketPrice.symbol == "MEBL")
                .order_by(MarketPrice.trade_date.desc())
                .limit(1)
            ).scalar_one()
        )
        assert _counts(db) == before


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
                ParsedPage(1, "Revenue table\nRevenue PKR 100 million\nQualification: unaudited."),
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


def base64_decode(value):
    import base64

    return base64.b64decode(value)


def test_mebl_oversized_fixture_is_a_production_shaped_reconstruction():
    subjects = [
        {
            "subject_id": f"subject-{index}",
            "entity": {"symbol": "MEBL", "type": "instrument", "resolution": "observed"},
            "event": {
                "event_id": f"event-{index // 3}",
                "classification": "results",
                "occurred_at": "2026-06-30T00:00:00Z",
                "materiality": "medium",
                "details": {"period": "Q2 2026", "source_status": "observed"},
            },
        }
        for index in range(233)
    ]
    references = [
        {
            "evidence_id": f"event-source-{index}",
            "source": {
                "title": f"MEBL official event source {index}",
                "url": f"https://example.test/mebl/{index}",
                "published_at": "2026-06-30T00:00:00Z",
            },
            "location": {"document_id": f"doc-{index // 4}", "page_number": index % 12 + 1},
            "snippet": "Observed issuer disclosure with material qualifications and period context.",
        }
        for index in range(224)
    ]
    fixture = {
        "fixture_kind": "reconstruction",
        "reconstruction_reason": "Exact historical serialized provider input was not retained.",
        "company": {"symbol": "MEBL", "name": "Meezan Bank Limited"},
        "event_subjects": subjects,
        "source_references": references,
    }
    component_bytes = {
        key: len(json.dumps(value, separators=(",", ":")).encode())
        for key, value in fixture.items()
    }
    assert len(subjects) == 233 and len(references) == 224
    assert component_bytes == {
        "fixture_kind": 16,
        "reconstruction_reason": 62,
        "company": 46,
        "event_subjects": 64402,
        "source_references": 67557,
    }


def test_assistant_mandate_ids_market_and_screening_are_database_reads(monkeypatch):
    from app.models.workstation import AnalysisRun, CompanyScreeningSnapshot, PortfolioIPSVersion
    seeded, user_id = _seed(monkeypatch)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        # Resolve the seeded user-owned portfolio through its actual stored IPS.
        version = db.scalar(select(PortfolioIPSVersion).where(PortfolioIPSVersion.status == "confirmed"))
        portfolio_id = version.portfolio_id
        registry = build_tool_registry()
        before = db.scalar(select(func.count()).select_from(AnalysisRun))
        summary = expand_model_data(registry.invoke("portfolio.summary", db, user, {"portfolio_id": portfolio_id}))
        assert summary["status"] == "ok"
        assert summary["sources"][0]["record_id"] == portfolio_id
        for holding in summary["data"]["holdings"]:
            assert holding["instrument_id"] == db.scalar(select(Instrument.id).where(Instrument.symbol == holding["symbol"]))
        ips = expand_model_data(registry.invoke("ips.compliance", db, user, {"portfolio_id": portfolio_id}))
        assert ips["data"]["mandate"]["ips_version_id"] == version.id
        assert ips["data"]["mandate"]["required_return"] == (str(version.required_return) if version.required_return is not None else None)
        assert ips["data"]["mandate"]["constraints"] == json.loads(version.constraints_json)
        overview = expand_model_data(registry.invoke("market.overview", db, user, {"sections": ["gainers", "sectors"], "limit": 3}))
        assert overview["status"] == "ok"
        expected = sorted(db.scalars(select(MarketPrice).where(MarketPrice.trade_date == date.fromisoformat(overview["data"]["gainers"]["effective_date"]))), key=lambda row: (row.change_percent, row.volume), reverse=True)[:3]
        assert [row["symbol"] for row in overview["data"]["gainers"]["records"]] == [row.symbol for row in expected]
        assert [Decimal(row["close"]) for row in overview["data"]["gainers"]["records"]] == [row.close for row in expected]
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        sector = expand_model_data(registry.invoke("research.company_sections", db, user, {"instrument_id": instrument.id, "sections": ["sector"]}))
        assert sector["data"]["sections"][0]["data"]["comparisons"] == []
        compared = expand_model_data(registry.invoke("research.company_sections", db, user, {"instrument_id": instrument.id, "sections": ["sector"], "sector_comparison_limit": 1}))
        assert len(compared["data"]["sections"][0]["data"]["comparisons"]) == 1

        universe = registry.invoke("market.universe", db, user, {"screening_fields": ["score", "income_growth"], "limit": 3})
        assert universe["status"] == "ok"
        assert "screening_as_of" in universe["data"]["columns"]
        assert universe["data"]["screening_coverage"]["returned_instruments"] == 3
        assert db.scalar(select(func.count()).select_from(AnalysisRun)) == before


def test_event_pagination_applies_offset_once(monkeypatch):
    from app.tools.research_tools import EventInput, _events
    # A database-like reader applies offset before returning limit+1 rows.
    events = [{"id": str(index), "sources": []} for index in range(7)]
    def reader(_db, **kwargs):
        offset = kwargs.get("offset", 0)
        return events[offset:offset + kwargs["limit"]]
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


def test_saved_quant_reuse_and_dependency_invalidation_do_not_write_on_reads(monkeypatch):
    from app.models.workstation import AnalysisRun, PortfolioIPSVersion
    from app.models.portfolio import Portfolio
    from app.services import workstation_service as service
    seeded, user_id = _seed(monkeypatch)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        portfolio_id = seeded["portfolio_id"]
        saved = service.portfolio_quant(db, user, portfolio_id)
        before = db.scalar(select(func.count()).select_from(AnalysisRun))
        numerical_calls = []
        original = service.return_matrix
        def track(prices):
            numerical_calls.append(True)
            return original(prices)
        original_performance = service.get_portfolio_performance
        def track_performance(*args, **kwargs):
            numerical_calls.append("performance")
            return original_performance(*args, **kwargs)
        monkeypatch.setattr(service, "get_portfolio_performance", track_performance)
        monkeypatch.setattr(service, "return_matrix", track)
        reused = service.portfolio_quant(db, user, portfolio_id, persist=False)
        assert reused["run_id"] == saved["run_id"]
        assert not numerical_calls
        # An older observation correction must invalidate, not just a new cutoff.
        price = db.scalar(select(MarketPrice).where(MarketPrice.symbol == "MEBL").order_by(MarketPrice.trade_date))
        price.close += Decimal("1")
        db.commit()
        corrected = service.portfolio_quant(db, user, portfolio_id, persist=False)
        assert corrected["run_id"] is None
        assert numerical_calls
        assert db.scalar(select(func.count()).select_from(AnalysisRun)) == before
        saved = service.portfolio_quant(db, user, portfolio_id)
        numerical_calls.clear()
        version = db.get(PortfolioIPSVersion, db.get(Portfolio, portfolio_id).selected_ips_version_id)
        constraints = json.loads(version.constraints_json)
        constraints["risk_free_series_key"] = "missing-observed-rate"
        version.constraints_json = json.dumps(constraints)
        db.commit()
        assert service.portfolio_quant(db, user, portfolio_id, persist=False)["run_id"] is None
        assert numerical_calls
        # Parameters also invalidate; no legacy result may satisfy the v2 lookup.
        saved = service.portfolio_quant(db, user, portfolio_id)
        numerical_calls.clear()
        assert service.portfolio_quant(db, user, portfolio_id, shrinkage=.3, persist=False)["run_id"] is None
        assert numerical_calls
        run = db.get(AnalysisRun, saved["run_id"])
        run.code_version = "quant-v1"
        db.commit()
        numerical_calls.clear()
        assert service.portfolio_quant(db, user, portfolio_id, persist=False)["run_id"] is None
        assert numerical_calls


def test_verifier_separates_acceptance_freshness_and_modeled_goal(monkeypatch):
    from app.models.workstation import AnalysisRun, PortfolioIPSVersion, ScenarioRun
    from app.models.portfolio import Portfolio
    from app.reasoning.allocation import AllocationProposal
    from app.services import allocation_verification as service
    from app.services.canonical_market_service import latest_price
    seeded, user_id = _seed(monkeypatch)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        portfolio = db.get(Portfolio, seeded["portfolio_id"])
        version = db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id)
        version.constraints_json = "{}"
        version.required_return = Decimal("100")  # deliberately infeasible test hurdle, not a forecast
        db.commit()
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        price = latest_price(db, instrument.symbol)
        class Clock:
            @staticmethod
            def now(_tz):
                return datetime.combine(price.trade_date, datetime.min.time(), tzinfo=UTC)
        monkeypatch.setattr(service, "datetime", Clock)
        proposal = AllocationProposal.model_validate({"legs": [{"instrument_id": instrument.id, "side": "buy", "gross_amount": str(price.close * 2)}]})
        before = {model: db.scalar(select(func.count()).select_from(model)) for model in (AnalysisRun, AllocationSet, ScenarioRun)}
        result = service.verify_allocation(db, user, portfolio.id, proposal, [instrument.id])
        assert result["accepted"] is True, result["errors"]
        assert result["checks"]["arithmetic_funding"]["status"] == "accepted"
        assert result["checks"]["modeled_goal"]["status"] == "below"
        assert result["checks"]["modeled_goal"]["shortfall"] > 0
        assert result["checks"]["price_freshness"]["status"] == "current"
        assert result["evidence_readiness"]["optimality"] == "not_established"
        assert result["legs"][0]["quantity"] == "2"
        # Advance using the same session policy, not an arbitrary stale-day cutoff.
        class LaterClock:
            @staticmethod
            def now(_tz):
                from datetime import timedelta
                return datetime.combine(price.trade_date, datetime.min.time(), tzinfo=UTC) + timedelta(days=7)
        monkeypatch.setattr(service, "datetime", LaterClock)
        stale = service.verify_allocation(db, user, portfolio.id, proposal, [instrument.id])
        assert stale["accepted"] is True
        assert stale["checks"]["price_freshness"]["status"] == "stale"
        assert stale["evidence_readiness"]["actionable_recommendation_eligible"] is False
        with monkeypatch.context() as scoped:
            original_summary = service.get_portfolio_summary
            scoped.setattr(service, "get_portfolio_summary", lambda *args: original_summary(*args).model_copy(update={"valuation_complete": False, "unpriced_symbols": ["MEBL"]}))
            incomplete = service.verify_allocation(db, user, portfolio.id, proposal, [instrument.id])
            assert incomplete["accepted"] is False
            assert "incomplete_portfolio_valuation" in incomplete["errors"]
            assert incomplete["evidence_readiness"]["actionable_recommendation_eligible"] is False
        with monkeypatch.context() as scoped:
            original_price = service.latest_price
            scoped.setattr(service, "latest_price", lambda session, symbol: None if symbol == "MEBL" else original_price(session, symbol))
            unavailable = service.verify_allocation(db, user, portfolio.id, proposal, [instrument.id])
            assert unavailable["accepted"] is False
            assert unavailable["checks"]["price_freshness"]["status"] == "unavailable"
            assert "missing_instrument_or_price" in unavailable["errors"]
        portfolio.selected_ips_version_id = None
        db.commit()
        missing = service.verify_allocation(db, user, portfolio.id, proposal, [instrument.id])
        assert missing["accepted"] is False
        assert "confirmed_ips_missing" in missing["errors"]
        assert missing["checks"]["modeled_goal"]["status"] == "unavailable"
        for model, count in before.items():
            assert db.scalar(select(func.count()).select_from(model)) == count
