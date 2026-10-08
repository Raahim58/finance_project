"""Company ratios for the company page, from stored facts and the latest stored price.

Every ratio needs same-period, same-basis, same-unit inputs that pass a plausibility
check. Extracted statement amounts are sometimes at different scales (a figure in PKR
millions beside one in full PKR), so a ratio that fails a check is reported as
unavailable with its reason instead of being shown wrong.
"""
from decimal import Decimal

PKR = {"PKR", "pkr"}
BASIS_ORDER = ("consolidated", "standalone")


def _num(value):
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _latest_annual(facts, key, *, basis=None, period_end=None):
    rows = [f for f in facts if f.get("taxonomy_key") == key and f.get("period_type") == "annual"
            and (f.get("unit") in PKR or f.get("currency") in PKR) and _num(f.get("value")) is not None
            and (basis is None or f.get("accounting_basis") == basis)
            and (period_end is None or str(f.get("period_end")) == str(period_end))]
    if not rows:
        return None
    newest = max(str(f["period_end"]) for f in rows)
    rows = [f for f in rows if str(f["period_end"]) == newest]
    for preferred in BASIS_ORDER:
        for row in rows:
            if row.get("accounting_basis") == preferred:
                return row
    return rows[0]


def _entry(value, *facts, warning=None):
    base = facts[0]
    return {"value": float(value), "period_end": str(base["period_end"]), "accounting_basis": base.get("accounting_basis"),
            "warning": warning, "inputs": [f.get("taxonomy_key") for f in facts],
            "document_ids": [f.get("document_id") for f in facts if f.get("document_id")]}


def display_ratios(facts: list[dict], price, shares_outstanding=None) -> dict:
    ratios: dict[str, dict] = {}
    unavailable: dict[str, str] = {}
    price = _num(price)
    shares = _num(shares_outstanding)

    eps = _latest_annual(facts, "earnings_per_share")
    if eps is None:
        unavailable["pe_ratio"] = "No annual earnings per share is stored"
    elif price is None or price <= 0:
        unavailable["pe_ratio"] = "No latest stored price"
    elif _num(eps["value"]) <= 0:
        unavailable["pe_ratio"] = f"Latest annual EPS ({eps['period_end']}) is not positive, so P/E is not meaningful"
    else:
        ratios["pe_ratio"] = _entry(price / _num(eps["value"]), eps,
            warning=f"Latest annual EPS ({eps['period_end']}) over the latest stored price; not a rolling 12-month figure.")

    dps = _latest_annual(facts, "dividend_per_share")
    if dps is None:
        unavailable["dividend_yield"] = "No annual dividend per share is stored"
    elif price is None or price <= 0:
        unavailable["dividend_yield"] = "No latest stored price"
    else:
        ratios["dividend_yield"] = _entry(_num(dps["value"]) / price, dps,
            warning=f"Annual dividend per share ({dps['period_end']}) over the latest stored price.")

    net_income = _latest_annual(facts, "net_income")
    revenue = _latest_annual(facts, "revenue", basis=net_income.get("accounting_basis"), period_end=net_income["period_end"]) if net_income else None
    if not revenue or not net_income:
        unavailable["net_margin"] = "Needs annual revenue and net income for the same period and basis"
    elif _num(revenue["value"]) == 0:
        unavailable["net_margin"] = "Revenue is zero"
    else:
        margin = _num(net_income["value"]) / _num(revenue["value"])
        if -5 <= margin <= 1:
            ratios["net_margin"] = _entry(margin, net_income, revenue)
        else:
            unavailable["net_margin"] = "Stored net income and revenue are not on a comparable scale"

    ebit = _latest_annual(facts, "ebit", basis=revenue.get("accounting_basis") if revenue else None, period_end=revenue["period_end"] if revenue else None) if revenue else None
    if not revenue or not ebit:
        unavailable["operating_margin"] = "Needs annual operating profit and revenue for the same period and basis"
    else:
        margin = _num(ebit["value"]) / _num(revenue["value"]) if _num(revenue["value"]) else None
        ni = _num(net_income["value"]) if net_income else None
        if margin is None or not -2 <= margin <= 1 or (ni is not None and ni > 0 and _num(ebit["value"]) < ni / 2):
            unavailable["operating_margin"] = "Stored operating profit is inconsistent with revenue and net income (likely a unit-scale error in extraction)"
        else:
            ratios["operating_margin"] = _entry(margin, ebit, revenue)

    equity = _latest_annual(facts, "equity", basis=net_income.get("accounting_basis") if net_income else None, period_end=net_income["period_end"] if net_income else None) if net_income else None
    if not net_income or not equity:
        for key in ("return_on_equity", "pb_ratio"):
            unavailable[key] = "Needs annual net income and equity for the same period and basis"
    else:
        equity_value = _num(equity["value"])
        roe = _num(net_income["value"]) / equity_value if equity_value else None
        if roe is None or not -2 <= roe <= 2:
            reason = "Stored equity and net income are not on a comparable scale (likely a unit-scale error in extraction)"
            unavailable["return_on_equity"] = reason
            unavailable["pb_ratio"] = reason
        else:
            ratios["return_on_equity"] = _entry(roe, net_income, equity, warning="Uses period-end equity, not average equity.")
            if shares and shares > 0 and price and equity_value > 0:
                ratios["pb_ratio"] = _entry(price / (equity_value / shares), equity, warning="Period-end equity over shares outstanding from the latest stored capitalization.")
            else:
                unavailable["pb_ratio"] = "Needs positive equity and shares outstanding"

    current_assets = _latest_annual(facts, "current_assets")
    current_liabilities = _latest_annual(facts, "current_liabilities", basis=current_assets.get("accounting_basis") if current_assets else None, period_end=current_assets["period_end"] if current_assets else None) if current_assets else None
    if current_assets and current_liabilities and _num(current_liabilities["value"]) > 0:
        value = _num(current_assets["value"]) / _num(current_liabilities["value"])
        if Decimal("0.01") <= value <= 50:
            ratios["current_ratio"] = _entry(value, current_assets, current_liabilities)
        else:
            unavailable["current_ratio"] = "Stored current assets and liabilities are not on a comparable scale"
    else:
        unavailable["current_ratio"] = "Needs annual current assets and current liabilities"
    unavailable.setdefault("quick_ratio", "Needs receivables and short-term investments, which are not stored")

    cash = _latest_annual(facts, "cash", period_end=current_liabilities["period_end"] if current_liabilities else None) if current_liabilities else None
    if cash and _num(cash["value"]) >= 0 and current_liabilities and _num(current_liabilities["value"]) > 0:
        ratios["cash_ratio"] = _entry(_num(cash["value"]) / _num(current_liabilities["value"]), cash, current_liabilities)
    else:
        unavailable["cash_ratio"] = "Needs non-negative cash and current liabilities for the same period"

    ocf = _latest_annual(facts, "operating_cash_flow")
    if ocf:
        ratios["operating_cash_flow"] = _entry(_num(ocf["value"]), ocf)
        capex = _latest_annual(facts, "capital_expenditure", basis=ocf.get("accounting_basis"), period_end=ocf["period_end"])
        if capex:
            ratios["free_cash_flow"] = _entry(_num(ocf["value"]) - abs(_num(capex["value"])), ocf, capex)
        else:
            unavailable["free_cash_flow"] = "Needs capital expenditure for the same period"
    else:
        unavailable["operating_cash_flow"] = "No annual operating cash flow is stored"
        unavailable["free_cash_flow"] = "No annual operating cash flow is stored"

    return {"ratios": ratios, "unavailable": {k: v for k, v in unavailable.items() if k not in ratios}}
