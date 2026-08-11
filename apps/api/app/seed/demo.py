"""Deterministic development seed for the complete portfolio-decision workflow.

All market observations remain explicitly mock data. The seed never stores an API
key and requires the operator to supply the development login password.
"""

import os
from datetime import date, timedelta

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.portfolio import Portfolio, PortfolioTransaction
from app.models.user import User
from app.models.workstation import AllocationSet, InvestorFinancialProfileVersion, MonitoringRule, MonitoringRun, OptimizerRun, ScenarioRun
from app.schemas.auth import SignupRequest
from app.schemas.portfolio import AllocationItemInput, AllocationSetCreate, PortfolioCreate, TransactionCreate
from app.schemas.workstation import IPSDraft, OptimizerRequest, ScenarioRequest, VersionDraft
from app.services.auth_service import create_user
from app.services.market_ingestion import generate_mock_market_data
from app.services.monitoring_service import run_monitoring
from app.services.portfolio_service import add_transaction, create_allocation_set, create_portfolio, get_portfolio_summary
from app.services.workstation_service import create_monitoring_rule, run_optimizer, run_scenario, save_ips_version, save_profile_version


DEMO_EMAIL = "portfolio.manager@example.com"
DEMO_PORTFOLIO = "PSX Decision Portfolio — Demo"


def seed_workstation() -> dict[str, object]:
    password = os.environ.get("DEMO_USER_PASSWORD")
    if not password or len(password) < 8:
        raise RuntimeError("Set DEMO_USER_PASSWORD to at least 8 characters before running the demo seed")
    with SessionLocal() as db:
        market = generate_mock_market_data(db, days=365)
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

        transaction_count = db.scalar(select(func.count(PortfolioTransaction.id)).where(PortfolioTransaction.portfolio_id == portfolio.id)) or 0
        if not transaction_count:
            opening_day = date.today() - timedelta(days=300)
            add_transaction(db, user, portfolio.id, TransactionCreate(symbol="CASH", transaction_type="opening_balance", amount=1_000_000, transaction_date=opening_day, source="deterministic_demo"))
            add_transaction(db, user, portfolio.id, TransactionCreate(symbol="MEBL", transaction_type="opening_balance", quantity=4_000, price=200, amount=0, transaction_date=opening_day, source="deterministic_demo"))
            add_transaction(db, user, portfolio.id, TransactionCreate(symbol="SYS", transaction_type="opening_balance", quantity=1_500, price=350, amount=0, transaction_date=opening_day, source="deterministic_demo"))
            add_transaction(db, user, portfolio.id, TransactionCreate(symbol="OGDC", transaction_type="opening_balance", quantity=3_000, price=110, amount=0, transaction_date=opening_day, source="deterministic_demo"))

        if portfolio.selected_ips_version_id is None:
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
                constraints={"long_only": True, "max_instrument_weight": 0.45, "max_sector_weight": 0.55, "min_cash_weight": 0.10},
            ), confirm=True)

        summary = get_portfolio_summary(db, user, portfolio.id)
        if not (db.scalar(select(func.count(AllocationSet.id)).where(AllocationSet.portfolio_id == portfolio.id, AllocationSet.kind == "target")) or 0):
            create_allocation_set(db, user, portfolio.id, AllocationSetCreate(
                kind="target",
                base_value=summary.total_value,
                assumptions={"source": "deterministic_demo", "execution": "proposal_only"},
                items=[
                    AllocationItemInput(symbol="MEBL", target_weight="0.30"),
                    AllocationItemInput(symbol="SYS", target_weight="0.25"),
                    AllocationItemInput(symbol="OGDC", target_weight="0.25"),
                    AllocationItemInput(symbol="CASH", target_weight="0.20", is_cash=True),
                ],
            ))

        if not (db.scalar(select(func.count(OptimizerRun.id)).where(OptimizerRun.portfolio_id == portfolio.id)) or 0):
            run_optimizer(db, user, portfolio.id, OptimizerRequest(objective="minimum_variance"))
        if not (db.scalar(select(func.count(ScenarioRun.id)).where(ScenarioRun.portfolio_id == portfolio.id)) or 0):
            run_scenario(db, user, portfolio.id, ScenarioRequest(name="Demo broad selloff", scenario_type="hypothetical", shocks={}, sector_shocks={"Banking": -0.12, "Technology": -0.16, "Oil & Gas Exploration": -0.10}))
        if not (db.scalar(select(func.count(MonitoringRule.id)).where(MonitoringRule.portfolio_id == portfolio.id)) or 0):
            create_monitoring_rule(db, user, portfolio.id, "concentration", {"maximum": 0.30})
        if not (db.scalar(select(func.count(MonitoringRun.id)).where(MonitoringRun.portfolio_id == portfolio.id, MonitoringRun.status == "completed")) or 0):
            run_monitoring(db, user, portfolio.id)

        return {"market": market, "user_email": DEMO_EMAIL, "portfolio_id": portfolio.id, "mock_data": True}


def main() -> None:
    result = seed_workstation()
    print(f"Seeded deterministic development workstation: {result}")


if __name__ == "__main__":
    main()
