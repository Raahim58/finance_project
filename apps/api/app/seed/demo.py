"""Deterministic development seed for the complete portfolio-decision workflow.

All market observations remain explicitly mock data. The seed never stores an API
key and requires the operator to supply the development login password.
"""

import json
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.portfolio import Portfolio, PortfolioTransaction
from app.models.market import MarketIngestionRun
from app.models.user import User
from app.models.document import Document
from app.models.workstation import AllocationSet, DataSource, Event, EventEntityLink, FinancialFact, Instrument, InvestorFinancialProfileVersion, MacroObservation, MacroSeries, MonitoringRule, MonitoringRun, OptimizerRun, PortfolioIPSVersion, ScenarioRun
from app.schemas.auth import SignupRequest
from app.schemas.portfolio import AllocationItemInput, AllocationSetCreate, PortfolioCreate, TransactionCreate
from app.schemas.workstation import IPSDraft, OptimizerRequest, ScenarioRequest, VersionDraft
from app.services.auth_service import create_user
from app.services.market_ingestion import generate_mock_market_data, record_market_ingestion_run
from app.services.monitoring_service import run_monitoring
from app.services.portfolio_service import add_transaction, create_allocation_set, create_portfolio, get_portfolio_summary
from app.services.workstation_service import create_monitoring_rule, run_optimizer, run_scenario, save_ips_version, save_profile_version
from app.services.rag_service import ParsedPage, create_document_from_pages


DEMO_EMAIL = "portfolio.manager@example.com"
DEMO_PORTFOLIO = "PSX Decision Portfolio — Demo"
DEMO_SEED_VERSION = "2026.3"

DEMO_MANAGEMENT_EVIDENCE = {
    "MEBL": "Synthetic management scenario: deposit mix shifts toward lower-cost current accounts while management prioritizes liquidity buffers and disciplined asset growth.",
    "SYS": "Synthetic management scenario: export revenue remains the main growth driver, creating positive PKR translation sensitivity alongside overseas demand and execution risk.",
    "OGDC": "Synthetic management scenario: cash generation is most sensitive to realized oil prices, production volumes, receivable collection and the PKR exchange rate.",
    "FFC": "Synthetic management scenario: margin resilience depends on gas availability and pricing, fertilizer volumes and distribution discipline.",
    "LUCK": "Synthetic management scenario: domestic cement demand and energy costs are the main operating sensitivities; capital allocation remains selective.",
    "HUBC": "Synthetic management scenario: cash conversion depends on receivable collection, capacity payments and fuel-indexation mechanics.",
    "ILP": "Synthetic management scenario: export orders and PKR translation support revenue while cotton, energy and customer concentration remain key sensitivities.",
    "MARI": "Synthetic management scenario: production growth and reserve replacement support the outlook; commodity prices and exploration execution remain key risks.",
}


def _seed_macro(db) -> int:
    source = db.scalar(select(DataSource).where(DataSource.name == "Deterministic Demo Macro"))
    if source is None:
        source = DataSource(name="Deterministic Demo Macro", source_type="macro", priority=999, freshness_sla_minutes=None, enabled=True, use_notes="Synthetic development-only macro series; never use as observed financial data.")
        db.add(source); db.flush()
    definitions = [
        ("sbp.tbill.3m_yield", "Demo 3-month government T-bill yield", "%", {"is_risk_free": True}, Decimal("12.5"), Decimal("-0.10")),
        ("pk.usd_pkr", "Demo USD/PKR exchange rate", "PKR per USD", {}, Decimal("278"), Decimal("0.35")),
        ("pbs.cpi.inflation_yoy", "Demo CPI inflation year-on-year", "%", {}, Decimal("9.5"), Decimal("-0.12")),
        ("worldbank.brent.usd", "Demo Brent crude price", "USD/bbl", {}, Decimal("78"), Decimal("0.20")),
    ]
    count = 0
    month_end = date.today().replace(day=1)
    for key, name, unit, metadata, base, step in definitions:
        series = db.scalar(select(MacroSeries).where(MacroSeries.key == key))
        if series is None:
            series = MacroSeries(key=key, name=name, unit=unit, frequency="monthly", source_id=source.id, metadata_json=json.dumps({**metadata, "data_classification": "synthetic_demo", "seed_version": DEMO_SEED_VERSION}))
            db.add(series); db.flush()
        for index in range(24):
            effective = month_end - timedelta(days=30 * (23 - index))
            effective = effective.replace(day=1)
            if db.scalar(select(MacroObservation.id).where(MacroObservation.series_id == series.id, MacroObservation.effective_date == effective, MacroObservation.is_selected.is_(True))):
                continue
            db.add(MacroObservation(series_id=series.id, effective_date=effective, release_at=datetime.combine(effective + timedelta(days=12), datetime.min.time(), tzinfo=UTC), value=base + step * index, revision=1, is_selected=True)); count += 1
    db.commit()
    return count


def _seed_company_research(db) -> dict[str, int]:
    instruments = list(db.scalars(select(Instrument).order_by(Instrument.symbol)))
    document_count = fact_count = event_count = 0
    for index, instrument in enumerate(instruments):
        metadata = json.loads(instrument.metadata_json or "{}")
        metadata.update({"data_classification": "synthetic_demo", "seed_version": DEMO_SEED_VERSION, "shariah_compliant": instrument.symbol not in {"HBL", "UBL", "MCB", "NBP", "BAHL"}, "factor_betas": {"market": round(0.75 + (index % 7) * 0.08, 2), "rates": round(((index % 5) - 2) * 0.35, 2), "pkr": round(((index % 6) - 3) * 0.18, 2), "oil": round(((index % 4) - 1) * 0.22, 2)}})
        instrument.metadata_json = json.dumps(metadata, sort_keys=True)
        for year in (2024, 2025):
            title = f"{instrument.symbol} synthetic demo annual facts {year} — {DEMO_SEED_VERSION}"
            document = db.scalar(select(Document).where(Document.title == title))
            scale = Decimal(1_000_000 + (index + 1) * 80_000)
            growth = Decimal("1.08") if year == 2025 else Decimal("1")
            revenue = scale * Decimal("100") * growth
            ebit = revenue * Decimal("0.18")
            net_income = revenue * Decimal("0.12")
            assets = scale * Decimal("240") * growth
            equity = assets * Decimal("0.42")
            cash = assets * Decimal("0.08")
            debt = assets * Decimal("0.25")
            if document is None:
                management = DEMO_MANAGEMENT_EVIDENCE.get(instrument.symbol, "Synthetic management scenario: operating priorities, demand sensitivity and balance-sheet discipline require review against current sourced filings.")
                text = f"SYNTHETIC DEMO DATA — NOT AN OBSERVED FILING\nAmounts in PKR\nRevenue {revenue}\nOperating profit {ebit}\nProfit after tax {net_income}\nTotal assets {assets}\nTotal equity {equity}\nCash and cash equivalents {cash}\nTotal debt {debt}\n\nManagement evidence (synthetic scenario, not a quotation)\n{management}\n"
                document = create_document_from_pages(db, [ParsedPage(page_number=1, text=text)], title=title, document_type="synthetic_demo_facts", symbol=instrument.symbol, fiscal_year=year, source_name="Deterministic Demo Seed", source_url=f"demo://company/{instrument.symbol}/{year}", published_date=date(year + 1, 3, 31), visibility="public", commit=False); document_count += 1
            facts = {"revenue": revenue, "ebit": ebit, "net_income": net_income, "assets": assets, "equity": equity, "cash": cash, "debt": debt}
            for taxonomy, value in facts.items():
                if db.scalar(select(FinancialFact.id).where(FinancialFact.instrument_id == instrument.id, FinancialFact.taxonomy_key == taxonomy, FinancialFact.period_end == date(year, 12, 31), FinancialFact.document_id == document.id)):
                    continue
                db.add(FinancialFact(instrument_id=instrument.id, taxonomy_key=taxonomy, period_type="annual", period_start=date(year, 1, 1), period_end=date(year, 12, 31), filing_date=date(year + 1, 3, 31), value=value, unit="PKR", currency="PKR", consolidated=True, document_id=document.id, page_number=1)); fact_count += 1
        if index < 12 and not db.scalar(select(Event.id).join(EventEntityLink, EventEntityLink.event_id == Event.id).where(EventEntityLink.entity_key == instrument.symbol, Event.title == f"{instrument.symbol} synthetic demo results update")):
            event = Event(event_type="results", title=f"{instrument.symbol} synthetic demo results update", occurred_at=datetime.combine(date.today() - timedelta(days=7 + index), datetime.min.time(), tzinfo=UTC), materiality="medium", direction="neutral", confidence=Decimal("1"), details_json=json.dumps({"data_classification": "synthetic_demo", "seed_version": DEMO_SEED_VERSION})); db.add(event); db.flush(); db.add(EventEntityLink(event_id=event.id, entity_type="instrument", entity_key=instrument.symbol, link_method="deterministic_demo", confidence=Decimal("1"))); event_count += 1
        announcement_title = f"{instrument.symbol} synthetic results announcement — {DEMO_SEED_VERSION}"
        if index < 12 and not db.scalar(select(Document).where(Document.title == announcement_title)):
            create_document_from_pages(
                db,
                [ParsedPage(page_number=1, text=f"SYNTHETIC DEMO EVENT — NOT AN OBSERVED ANNOUNCEMENT\n{instrument.symbol} published a synthetic results update for workflow testing.\n{DEMO_MANAGEMENT_EVIDENCE.get(instrument.symbol, 'Review operating progress and current source evidence before drawing a conclusion.')}\n")],
                title=announcement_title,
                document_type="announcement",
                symbol=instrument.symbol,
                source_name="Deterministic Demo Seed",
                source_url=f"demo://announcement/{instrument.symbol}/{DEMO_SEED_VERSION}",
                published_date=date.today() - timedelta(days=7 + index),
                visibility="public",
                commit=False,
            )
            document_count += 1
    db.commit()
    return {"documents": document_count, "facts": fact_count, "events": event_count}


def _seed_macro_research(db) -> int:
    title = f"Pakistan synthetic macro brief — {DEMO_SEED_VERSION}"
    if db.scalar(select(Document).where(Document.title == title)):
        return 0
    create_document_from_pages(
        db,
        [ParsedPage(page_number=1, text="SYNTHETIC DEMO MACRO BRIEF — NOT OBSERVED DATA\nInflation is falling in the selected demo series. The PKR per USD series is rising, the three-month government T-bill yield is falling, and Brent is rising. These directions route stress templates; they are not forecasts or investment recommendations.\n")],
        title=title,
        document_type="macro_brief",
        source_name="Deterministic Demo Seed",
        source_url=f"demo://macro/{DEMO_SEED_VERSION}",
        published_date=date.today(),
        visibility="public",
        commit=False,
    )
    db.commit()
    return 1


def seed_workstation() -> dict[str, object]:
    password = os.environ.get("DEMO_USER_PASSWORD")
    if not password or len(password) < 8:
        raise RuntimeError("Set DEMO_USER_PASSWORD to at least 8 characters before running the demo seed")
    with SessionLocal() as db:
        market = generate_mock_market_data(db, days=365)
        macro_count = _seed_macro(db)
        research = _seed_company_research(db)
        research["macro_documents"] = _seed_macro_research(db)
        if not db.scalar(select(func.count()).select_from(MarketIngestionRun).where(MarketIngestionRun.used_provider == "mock")):
            record_market_ingestion_run(db, mode="mock", attempted_provider="mock", used_provider="mock", status="success", started_at=datetime.now(UTC), latest_trade_date=date.today(), records_written=int(market["prices"]), message=f"Deterministic demo seed {DEMO_SEED_VERSION}; synthetic data only.")
        user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = create_user(db, SignupRequest(email=DEMO_EMAIL, password=password, full_name="Demo Portfolio Manager"))

        portfolio = db.scalar(select(Portfolio).where(Portfolio.user_id == user.id, Portfolio.name == DEMO_PORTFOLIO))
        if portfolio is None:
            created = create_portfolio(db, user, PortfolioCreate(
                name=DEMO_PORTFOLIO,
                description="Deterministic development-only portfolio decision workflow.",
                goal_summary="Grow capital over seven years within a confirmed long-only mandate.",
            ))
            portfolio = db.get(Portfolio, created.id)

        profile_count = db.scalar(select(func.count(InvestorFinancialProfileVersion.id)).where(InvestorFinancialProfileVersion.user_id == user.id)) or 0
        if not profile_count:
            save_profile_version(db, user, VersionDraft(data={
                "liquid_assets": 8_000_000,
                "short_term_liabilities": 500_000,
                "annual_expenses": 1_200_000,
                "horizon_years": 7,
                "portfolio_income_dependence": "low",
                "drawdown_capacity": "moderate",
                "risk_capacity": "moderate",
                "willingness_answers": [3, 4, 3],
                "confirmed_overall_risk_tolerance": "moderate",
                "data_classification": "synthetic_demo",
            }), confirm=True)

        transaction_symbols = set(db.scalars(select(PortfolioTransaction.symbol).where(PortfolioTransaction.portfolio_id == portfolio.id)))
        opening_day = date.today() - timedelta(days=300)
        if "CASH" not in transaction_symbols:
            add_transaction(db, user, portfolio.id, TransactionCreate(symbol="CASH", transaction_type="opening_balance", amount=1_000_000, transaction_date=opening_day, source="deterministic_demo"))
        demo_positions = {"MEBL": (4_000, 200), "SYS": (1_500, 350), "OGDC": (3_000, 110), "FFC": (2_200, 150), "LUCK": (350, 800), "HUBC": (2_000, 130), "ILP": (3_000, 60), "MARI": (350, 600)}
        for symbol, (quantity, price) in demo_positions.items():
            if symbol not in transaction_symbols:
                add_transaction(db, user, portfolio.id, TransactionCreate(symbol=symbol, transaction_type="opening_balance", quantity=quantity, price=price, amount=0, transaction_date=opening_day, source="deterministic_demo"))

        selected_ips = db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id) if portfolio.selected_ips_version_id else None
        selected_constraints = json.loads(selected_ips.constraints_json) if selected_ips else {}
        if selected_constraints.get("notes") != f"Synthetic demo seed {DEMO_SEED_VERSION}":
            save_ips_version(db, user, portfolio.id, IPSDraft(
                goal="Grow the portfolio to fund a long-horizon capital objective while retaining liquidity.",
                starting_capital=2_655_000,
                target_value=4_200_000,
                horizon_years=7,
                benchmark_symbol="HBL",
                risk_capacity="moderate",
                risk_willingness="moderate",
                overall_risk_tolerance="moderate",
                liquidity_requirement=250_000,
                leverage_allowed=False,
                derivatives_allowed=False,
                constraints={"long_only": True, "max_instrument_weight": 0.30, "max_sector_weight": 0.40, "min_cash_weight": 0.10, "target_volatility": 0.18, "target_beta": 1.0, "risk_budget_tolerance": 0.08, "risk_budgets": {"MEBL": 0.18, "SYS": 0.18, "OGDC": 0.12, "FFC": 0.12, "LUCK": 0.10, "HUBC": 0.10, "ILP": 0.10, "MARI": 0.10}, "profile_policy_note": "Moderate risk tolerance is implemented through explicit 18% volatility and 1.0 beta ceilings, 10% minimum cash, diversification caps and security risk budgets; the label itself never changes optimizer math.", "notes": f"Synthetic demo seed {DEMO_SEED_VERSION}"},
            ), confirm=True)
            selected_ips = db.get(PortfolioIPSVersion, portfolio.selected_ips_version_id)
            selected_constraints = json.loads(selected_ips.constraints_json) if selected_ips else {}

        summary = get_portfolio_summary(db, user, portfolio.id)
        if not (db.scalar(select(func.count(AllocationSet.id)).where(AllocationSet.portfolio_id == portfolio.id, AllocationSet.kind == "target", AllocationSet.assumptions_json.contains(DEMO_SEED_VERSION))) or 0):
            create_allocation_set(db, user, portfolio.id, AllocationSetCreate(
                kind="target",
                base_value=summary.total_value,
                assumptions={"source": "deterministic_demo", "seed_version": DEMO_SEED_VERSION, "execution": "proposal_only"},
                items=[
                    AllocationItemInput(symbol="MEBL", target_weight="0.16"), AllocationItemInput(symbol="SYS", target_weight="0.14"),
                    AllocationItemInput(symbol="OGDC", target_weight="0.12"), AllocationItemInput(symbol="FFC", target_weight="0.12"),
                    AllocationItemInput(symbol="LUCK", target_weight="0.10"), AllocationItemInput(symbol="HUBC", target_weight="0.08"),
                    AllocationItemInput(symbol="ILP", target_weight="0.08"), AllocationItemInput(symbol="MARI", target_weight="0.08"),
                    AllocationItemInput(symbol="CASH", target_weight="0.12", is_cash=True),
                ],
            ))

        optimizer_payloads = [
            OptimizerRequest(objective="minimum_variance"),
            OptimizerRequest(objective="max_sharpe", expected_return_method="historical_shrunk"),
            OptimizerRequest(objective="target_volatility_maximum_return", expected_return_method="historical_shrunk", target_volatility=0.18),
            OptimizerRequest(objective="risk_parity"),
        ]
        seed_cutoff = selected_ips.confirmed_at if selected_ips and selected_constraints.get("notes") == f"Synthetic demo seed {DEMO_SEED_VERSION}" else datetime.min.replace(tzinfo=UTC)
        existing_objectives = set(db.scalars(select(OptimizerRun.objective).where(OptimizerRun.portfolio_id == portfolio.id, OptimizerRun.created_at >= seed_cutoff)))
        for payload in optimizer_payloads:
            if payload.objective not in existing_objectives:
                run_optimizer(db, user, portfolio.id, payload)
        scenario_payloads = [
            ScenarioRequest(name="Demo broad selloff", sector_shocks={"Banking": -0.12, "Technology": -0.16, "Oil & Gas Exploration": -0.10}),
            ScenarioRequest(name="Demo rates +200 bps", factor_shocks={"rates": 0.02}),
            ScenarioRequest(name="Demo PKR depreciation 15%", factor_shocks={"pkr": -0.15}),
            ScenarioRequest(name="Demo oil price spike 25%", factor_shocks={"oil": 0.25}),
            ScenarioRequest(name="Demo banking stress", sector_shocks={"Banking": -0.18}),
        ]
        existing_scenarios = set(db.scalars(select(ScenarioRun.name).where(ScenarioRun.portfolio_id == portfolio.id, ScenarioRun.created_at >= seed_cutoff)))
        for payload in scenario_payloads:
            if payload.name not in existing_scenarios:
                run_scenario(db, user, portfolio.id, payload)
        monitoring_rules = {
            "concentration": {"maximum": 0.18},
            "stale_data": {},
            "drawdown": {"maximum": 0.50},
            "volatility": {"maximum": 0.50},
            "var": {"maximum": 0.20},
            "liquidity": {"minimum_daily_volume": 1, "minimum_traded_value": 1},
            "event": {"lookback_hours": 720, "minimum_materiality": "medium"},
            "ingestion_failure": {"lookback_hours": 24},
        }
        for rule_type, threshold in monitoring_rules.items():
            existing_rule = db.scalar(select(MonitoringRule).where(MonitoringRule.portfolio_id == portfolio.id, MonitoringRule.rule_type == rule_type))
            if existing_rule is None:
                create_monitoring_rule(db, user, portfolio.id, rule_type, threshold)
            else:
                existing_rule.threshold_json = json.dumps(threshold, sort_keys=True)
                existing_rule.enabled = True
        db.commit()
        run_monitoring(db, user, portfolio.id)

        return {"market": market, "macro_observations_added": macro_count, "research": research, "user_email": DEMO_EMAIL, "portfolio_id": portfolio.id, "seed_version": DEMO_SEED_VERSION, "mock_data": True}


def main() -> None:
    result = seed_workstation()
    print(f"Seeded deterministic development workstation: {result}")


if __name__ == "__main__":
    main()
