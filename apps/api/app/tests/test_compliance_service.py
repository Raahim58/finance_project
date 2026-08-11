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
