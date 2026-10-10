"""Offline company read tools contracts and fixtures."""

import json
from datetime import date
from decimal import Decimal
from sqlalchemy import func, select
from app.db.session import SessionLocal
from app.models.market import MarketPrice
from app.models.user import User
from app.models.workstation import FinancialFact, Instrument
from app.tools import build_tool_registry
from app.tools.registry import expand_model_data
from app.tests.support.tools import _seed, _counts
import pytest

pytestmark = pytest.mark.usefixtures("database")


def test_company_sections_preserve_period_unit_source_and_have_no_side_effects(monkeypatch):
    prohibited_calls = []

    def prohibited(*_args, **_kwargs):
        prohibited_calls.append(True)
        raise AssertionError("prohibited side effect")

    monkeypatch.setattr("app.ai.providers.http_placeholders.AnthropicProvider.chat", prohibited)
    _, user_id = _seed(monkeypatch)
    with SessionLocal.begin() as db:
        user = db.get(User, user_id)
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        db.add_all([
            FinancialFact(
                instrument_id=instrument.id, taxonomy_key="net_income", period_type="annual",
                period_end=date(2023, 12, 31), unit="million", currency="PKR", consolidated=True,
                value=Decimal(value), source_label=source,
            )
            for value, source in [("101.25", "Issuer annual report"), ("99.75", "Exchange filing")]
        ])
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
        # Legacy secondary observations (no verified fiscal period, duration or
        # basis) fail closed: stored, but never exact company facts.
        assert {row["period_end"] for row in facts} == {"2023-12-31"}
        assert data["measurements"][0]["size_kind"] == "estimate"
        assert set(result["data"]["sections"]) == {"columns", "rows"}
        assert _counts(db) == before
        assert prohibited_calls == []

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


def test_assistant_mandate_ids_market_and_screening_are_database_reads(monkeypatch):
    from app.models.workstation import AnalysisRun, PortfolioIPSVersion

    seeded, user_id = _seed(monkeypatch)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        # Resolve the seeded user-owned portfolio through its actual stored IPS.
        version = db.scalar(
            select(PortfolioIPSVersion).where(PortfolioIPSVersion.status == "confirmed")
        )
        portfolio_id = version.portfolio_id
        registry = build_tool_registry()
        before = db.scalar(select(func.count()).select_from(AnalysisRun))
        summary = expand_model_data(
            registry.invoke("portfolio.summary", db, user, {"portfolio_id": portfolio_id})
        )
        assert summary["status"] == "ok"
        assert summary["sources"][0]["record_id"] == portfolio_id
        for holding in summary["data"]["holdings"]:
            assert holding["instrument_id"] == db.scalar(
                select(Instrument.id).where(Instrument.symbol == holding["symbol"])
            )
        ips = expand_model_data(
            registry.invoke("ips.compliance", db, user, {"portfolio_id": portfolio_id})
        )
        assert ips["data"]["mandate"]["ips_version_id"] == version.id
        assert ips["data"]["mandate"]["required_return"] == (
            str(version.required_return) if version.required_return is not None else None
        )
        assert ips["data"]["mandate"]["constraints"] == json.loads(version.constraints_json)
        overview = expand_model_data(
            registry.invoke(
                "market.overview", db, user, {"sections": ["gainers", "sectors"], "limit": 3}
            )
        )
        assert overview["status"] == "ok"
        expected = sorted(
            db.scalars(
                select(MarketPrice).where(
                    MarketPrice.trade_date
                    == date.fromisoformat(overview["data"]["gainers"]["effective_date"])
                )
            ),
            key=lambda row: (row.change_percent, row.volume),
            reverse=True,
        )[:3]
        assert [row["symbol"] for row in overview["data"]["gainers"]["records"]] == [
            row.symbol for row in expected
        ]
        assert [Decimal(row["close"]) for row in overview["data"]["gainers"]["records"]] == [
            row.close for row in expected
        ]
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        sector = expand_model_data(
            registry.invoke(
                "research.company_sections",
                db,
                user,
                {"instrument_id": instrument.id, "sections": ["sector"]},
            )
        )
        assert sector["data"]["sections"][0]["data"]["comparisons"] == []
        compared = expand_model_data(
            registry.invoke(
                "research.company_sections",
                db,
                user,
                {
                    "instrument_id": instrument.id,
                    "sections": ["sector"],
                    "sector_comparison_limit": 1,
                },
            )
        )
        assert len(compared["data"]["sections"][0]["data"]["comparisons"]) == 1

        universe = registry.invoke(
            "market.universe",
            db,
            user,
            {"screening_fields": ["score", "income_growth"], "limit": 3},
        )
        assert universe["status"] == "ok"
        assert "screening_as_of" in universe["data"]["columns"]
        assert universe["data"]["screening_coverage"]["returned_instruments"] == 3
        assert db.scalar(select(func.count()).select_from(AnalysisRun)) == before


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
        price = db.scalar(
            select(MarketPrice).where(MarketPrice.symbol == "MEBL").order_by(MarketPrice.trade_date)
        )
        price.close += Decimal("1")
        db.commit()
        corrected = service.portfolio_quant(db, user, portfolio_id, persist=False)
        assert corrected["run_id"] is None
        assert numerical_calls
        assert db.scalar(select(func.count()).select_from(AnalysisRun)) == before
        saved = service.portfolio_quant(db, user, portfolio_id)
        numerical_calls.clear()
        version = db.get(
            PortfolioIPSVersion, db.get(Portfolio, portfolio_id).selected_ips_version_id
        )
        constraints = json.loads(version.constraints_json)
        constraints["risk_free_series_key"] = "missing-observed-rate"
        version.constraints_json = json.dumps(constraints)
        db.commit()
        assert service.portfolio_quant(db, user, portfolio_id, persist=False)["run_id"] is None
        assert numerical_calls
        # Parameters also invalidate; no legacy result may satisfy the v2 lookup.
        saved = service.portfolio_quant(db, user, portfolio_id)
        numerical_calls.clear()
        assert (
            service.portfolio_quant(db, user, portfolio_id, shrinkage=0.3, persist=False)["run_id"]
            is None
        )
        assert numerical_calls
        run = db.get(AnalysisRun, saved["run_id"])
        run.code_version = "quant-v1"
        db.commit()
        numerical_calls.clear()
        assert service.portfolio_quant(db, user, portfolio_id, persist=False)["run_id"] is None
        assert numerical_calls
