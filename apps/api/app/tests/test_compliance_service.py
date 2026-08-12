from app.services.compliance_service import evaluate_ips_constraints


def test_shared_compliance_distinguishes_pass_breach_and_not_evaluated():
    result = evaluate_ips_constraints(
        {
            "max_instrument_weight": 0.45,
            "max_sector_weight": 0.55,
            "min_cash_weight": 0.10,
            "shariah_only": True,
            "target_beta": 0.9,
        },
        [
            {"symbol": "SYS", "weight": 0.50, "sector": "Technology", "shariah_eligible": None},
            {"symbol": "MEBL", "weight": 0.35, "sector": "Banking", "shariah_eligible": None},
            {"symbol": "CASH", "weight": 0.15, "sector": "Cash"},
        ],
        ips_version_id="ips-1",
        context="proposed",
    )

    by_code = {check["code"]: check for check in result["checks"]}
    assert result["status"] == "BREACH"
    assert result["compliant"] is False
    assert by_code["max_instrument_weight"]["status"] == "BREACH"
    assert by_code["min_cash_weight"]["status"] == "PASS"
    assert by_code["shariah_eligibility"]["status"] == "NOT_EVALUATED"
    assert by_code["target_beta"]["status"] == "NOT_EVALUATED"


def test_availability_does_not_masquerade_as_a_breach():
    result = evaluate_ips_constraints(
        {"max_instrument_weight": 0.60},
        [{"symbol": "MEBL", "weight": 0.50, "sector": None}, {"symbol": "CASH", "weight": 0.50}],
        ips_version_id="ips-2",
        valuation_complete=False,
        unpriced_symbols=["OGDC"],
    )

    assert result["status"] == "NOT_EVALUATED"
    assert result["compliant"] is False
    assert result["violations"] == []
    assert any(check["code"] == "valuation_complete" for check in result["not_evaluated"])


def test_modeled_constraints_are_evaluated_and_non_applicable_is_not_missing():
    result = evaluate_ips_constraints(
        {
            "max_instrument_weight": 0.60,
            "target_beta": 1.0,
            "target_volatility": 0.18,
            "risk_budgets": {"SYS": 0.50, "MEBL": 0.50},
            "risk_budget_tolerance": 0.05,
            "liquidity_requirement": 250_000,
            "shariah_only": False,
        },
        [
            {"symbol": "SYS", "weight": 0.40, "sector": "Technology"},
            {"symbol": "MEBL", "weight": 0.40, "sector": "Banking"},
            {"symbol": "CASH", "weight": 0.20, "sector": "Cash"},
        ],
        ips_version_id="ips-modeled",
        modeled_inputs={
            "portfolio_beta": 0.82,
            "portfolio_volatility": 0.14,
            "risk_contributions": {"SYS": 0.52, "MEBL": 0.48},
            "liquid_assets": 300_000,
            "data_cutoff": "2026-08-12",
        },
    )

    by_code = {check["code"]: check for check in result["checks"]}
    assert result["status"] == "PASS"
    assert by_code["target_beta"]["status"] == "PASS"
    assert by_code["target_volatility"]["status"] == "PASS"
    assert by_code["risk_budgets"]["status"] == "PASS"
    assert by_code["liquidity_requirement"]["status"] == "PASS"
    assert by_code["shariah_eligibility"]["severity"] == "not_applicable"
    assert all(check["code"] != "shariah_eligibility" for check in result["not_evaluated"])


def test_modeled_constraint_breaches_are_explicit():
    result = evaluate_ips_constraints(
        {"target_beta": 0.80, "target_volatility": 0.12, "liquidity_requirement": 500_000},
        [{"symbol": "SYS", "weight": 0.90, "sector": "Technology"}, {"symbol": "CASH", "weight": 0.10, "sector": "Cash"}],
        ips_version_id="ips-breach",
        modeled_inputs={"portfolio_beta": 1.05, "portfolio_volatility": 0.16, "liquid_assets": 100_000},
    )

    assert result["status"] == "BREACH"
    assert {check["code"] for check in result["violations"]} == {"target_beta", "target_volatility", "liquidity_requirement"}
