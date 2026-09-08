"""Proposals contain requested gross amounts; only verification supplies quantities."""
from decimal import Decimal, ROUND_FLOOR
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class AllocationLeg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument_id: str
    side: Literal["buy", "sell"]
    gross_amount: Decimal = Field(gt=0, allow_inf_nan=False)


class AllocationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    legs: list[AllocationLeg] = Field(default_factory=list, max_length=20)
    rationale: str = Field(default="", max_length=2000)


def calculate_allocation(proposal, positions, cash, instruments):
    """Pure gross-cash arithmetic; never fabricates execution prices or costs."""
    quantities = {key: Decimal(str(value)) for key, value in positions.items()}
    initial = dict(quantities)
    cash = Decimal(str(cash))
    initial_cash = cash
    legs = []
    errors = []
    seen = set()
    for leg in proposal.legs:
        instrument = instruments.get(leg.instrument_id)
        if not instrument or instrument.get("price") is None:
            errors.append("missing_instrument_or_price")
            continue
        if leg.instrument_id in seen:
            errors.append("duplicate_instrument_leg")
            continue
        seen.add(leg.instrument_id)
        price = Decimal(str(instrument["price"]))
        lot = Decimal(str(instrument.get("lot_size") or 1))
        if not price.is_finite() or price <= 0 or not lot.is_finite() or lot <= 0:
            errors.append("invalid_price_or_lot")
            continue
        quantity = (leg.gross_amount / price / lot).to_integral_value(rounding=ROUND_FLOOR) * lot
        if quantity <= 0:
            errors.append("amount_below_one_lot")
            continue
        if leg.side == "sell" and quantity > quantities.get(leg.instrument_id, Decimal(0)):
            errors.append("overselling")
            continue
        gross = quantity * price
        direction = 1 if leg.side == "buy" else -1
        quantities[leg.instrument_id] = quantities.get(leg.instrument_id, Decimal(0)) + direction * quantity
        cash -= direction * gross
        statement = f"{leg.side.title()} {quantity} shares of {instrument["symbol"]} for gross {instrument.get("currency", "PKR")} {gross}."
        legs.append({"required_statement": statement, "instrument_id": leg.instrument_id, "symbol": instrument["symbol"],
            "side": leg.side, "quantity": str(quantity), "gross_amount": str(gross),
            "price": str(price), "currency": str(instrument.get("currency", "PKR")),
            "lot_size": str(lot),
            "quantity_basis": "stored_lot_size" if instrument.get("lot_size") else "provisional_whole_shares"})
    if cash < 0:
        errors.append("unfunded_purchase")
    def values(qty, balance):
        result = {key: value * Decimal(str(instruments[key]["price"])) for key, value in qty.items()
                  if value and key in instruments and instruments[key].get("price") is not None}
        result["CASH"] = balance
        return result
    before = values(initial, initial_cash)
    after = values(quantities, cash)
    total = sum(before.values())
    if total <= 0:
        errors.append("non_positive_portfolio_value")
    def weights(amounts):
        return {key: float(value / total) if total > 0 else 0 for key, value in amounts.items()}
    return {"accepted": not errors, "errors": errors, "legs": legs,
        "current_weights": weights(before), "proposed_weights": weights(after),
        "current_cash": str(initial_cash), "proposed_cash": str(cash),
        "cost_note": "Brokerage and taxes apply separately and are unavailable; quantities are provisional and affordability is gross, not net.",
        "financial_state_mutated": False}
