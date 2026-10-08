from app.services.company_ratios import display_ratios


def fact(key, value, period="2025-12-31", basis="consolidated", ptype="annual"):
    return {"taxonomy_key": key, "value": value, "unit": "PKR", "currency": "PKR", "period_end": period,
            "period_type": ptype, "accounting_basis": basis, "document_id": f"d-{key}"}


def test_hubc_like_facts_give_safe_ratios_and_explain_the_rest():
    facts = [fact("revenue", 83351000000), fact("net_income", 19079000000), fact("earnings_per_share", 14.71),
             fact("dividend_per_share", 6.5), fact("ebit", 175270000), fact("equity", 54925), fact("assets", 160008),
             fact("cash", -18212125000, basis="standalone")]
    result = display_ratios(facts, "199.80", 1297154400)
    ratios, missing = result["ratios"], result["unavailable"]
    assert round(ratios["pe_ratio"]["value"], 2) == round(199.80 / 14.71, 2)
    assert round(ratios["dividend_yield"]["value"], 4) == round(6.5 / 199.80, 4)
    assert round(ratios["net_margin"]["value"], 3) == round(19079 / 83351, 3)
    assert "operating_margin" in missing and "scale" in missing["operating_margin"]
    assert "return_on_equity" in missing and "pb_ratio" in missing
    assert "cash_ratio" in missing and "quick_ratio" in missing
    assert not set(ratios) & set(missing)


def test_negative_eps_and_missing_price_are_not_meaningful():
    assert "not positive" in display_ratios([fact("earnings_per_share", -2)], "100")["unavailable"]["pe_ratio"]
    assert display_ratios([fact("earnings_per_share", 5)], None)["unavailable"]["pe_ratio"] == "No latest stored price"


def test_consistent_balance_sheet_gives_roe_pb_and_current_ratio():
    facts = [fact("net_income", 100), fact("equity", 800), fact("current_assets", 500), fact("current_liabilities", 250), fact("cash", 100)]
    result = display_ratios(facts, "50", 10)
    assert result["ratios"]["return_on_equity"]["value"] == 0.125
    assert result["ratios"]["pb_ratio"]["value"] == 50 / 80
    assert result["ratios"]["current_ratio"]["value"] == 2
    assert result["ratios"]["cash_ratio"]["value"] == 0.4
