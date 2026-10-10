"""Offline allocation calculation contracts and fixtures."""

from decimal import Decimal
import pytest
from app.reasoning.allocation import AllocationProposal, calculate_allocation


def calculate(legs, cash="1000", holdings=None, lot=None):
    proposal = AllocationProposal.model_validate({"legs": legs})
    instruments = {
        "a": {"symbol": "MEBL", "price": "100", "lot_size": lot},
        "b": {"symbol": "SYS", "price": "50"},
    }
    return calculate_allocation(proposal, holdings or {}, cash, instruments)


def test_cash_purchase_and_costs_are_gross_and_provisional():
    result = calculate([{"instrument_id": "a", "side": "buy", "gross_amount": "950"}])
    assert result["accepted"] and result["legs"][0]["quantity"] == "9"
    assert result["proposed_cash"] == "100"
    assert "taxes" in result["cost_note"] and not result["financial_state_mutated"]


def test_explicit_sale_funds_switch_independent_of_leg_order():
    legs = [
        {"instrument_id": "b", "side": "buy", "gross_amount": "1000"},
        {"instrument_id": "a", "side": "sell", "gross_amount": "1000"},
    ]
    result = calculate(legs, cash="0", holdings={"a": Decimal(10)})
    reverse = calculate(list(reversed(legs)), cash="0", holdings={"a": Decimal(10)})
    assert result["accepted"] and result["proposed_cash"] == "0"
    assert result["proposed_weights"] == reverse["proposed_weights"]


@pytest.mark.parametrize(
    "side,cash,holdings,error",
    [("sell", "0", {"a": 1}, "overselling"), ("buy", "0", {"a": 1}, "unfunded_purchase")],
)
def test_invalid_funding_rejected(side, cash, holdings, error):
    result = calculate(
        [{"instrument_id": "a", "side": side, "gross_amount": "1000"}], cash, holdings
    )
    assert not result["accepted"] and error in result["errors"]


def test_stored_lot_rule():
    result = calculate([{"instrument_id": "a", "side": "buy", "gross_amount": "950"}], lot=5)
    assert result["legs"][0]["quantity"] == "5"
    assert result["legs"][0]["quantity_basis"] == "stored_lot_size"


def test_shariah_aliases_agree_or_remain_unknown():
    from app.services.compliance_service import shariah_eligibility

    assert shariah_eligibility({"shariah_compliant": True}) is True
    assert shariah_eligibility({"shariah_eligible": False}) is False
    assert shariah_eligibility({"shariah_eligible": True, "shariah_compliant": False}) is None
    assert shariah_eligibility({}) is None
    assert shariah_eligibility({"shariah_eligible": "true"}) is None
