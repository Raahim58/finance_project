"""Observed company risk, separate from screening growth/margin/liquidity metrics."""
from datetime import date, timedelta
from app.domain.quant import return_matrix, risk_metrics
from app.services.canonical_market_service import price_series


def company_risk(db, symbol, as_of=None):
    as_of = as_of or date.today()
    prices = price_series(db, symbol, start=as_of - timedelta(days=550), end=as_of)
    if len(prices) < 31:
        return None
    returns = return_matrix([[float(row.close) for row in prices]])[:, 0]
    return {"method": "observed_daily_price_risk_v1", "as_of": prices[-1].trade_date,
            "adjustment_states": sorted({row.adjustment_state for row in prices}),
            "metrics": risk_metrics(returns).to_dict()}
