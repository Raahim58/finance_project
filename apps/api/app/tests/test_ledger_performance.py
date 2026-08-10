from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.market import MarketPrice
from app.models.workstation import CorporateAction, Instrument, PortfolioCashSnapshot, PortfolioPositionSnapshot
from app.services.ledger_service import apply_recorded_corporate_actions
from app.services.market_ingestion import generate_mock_market_data


def _auth(client):
    response = client.post(
        "/auth/signup",
        json={"email": "ledger-performance@example.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _portfolio_and_prices(client):
    with SessionLocal() as db:
        generate_mock_market_data(db, days=8, end_date=date(2026, 8, 7))
        prices = list(
            db.scalars(
                select(MarketPrice)
                .where(MarketPrice.symbol == "MEBL")
                .order_by(MarketPrice.trade_date)
            )
        )
    headers = _auth(client)
    portfolio_id = client.post("/portfolios", headers=headers, json={"name": "Accounting"}).json()["id"]
    return headers, portfolio_id, prices


def test_cash_is_value_but_never_unrealized_profit(client):
    headers, portfolio_id, _ = _portfolio_and_prices(client)
    response = client.post(
        f"/portfolios/{portfolio_id}/transactions",
        headers=headers,
        json={"transaction_type": "deposit", "amount": "10000", "transaction_date": "2026-08-07"},
    )
    assert response.status_code == 201

    summary = client.get(f"/portfolios/{portfolio_id}/summary", headers=headers).json()
    assert Decimal(summary["total_value"]) == Decimal("10000")
    assert Decimal(summary["unrealized_gain_loss"]) == Decimal("0")
    assert Decimal(summary["net_external_contributions"]) == Decimal("10000")
    assert Decimal(summary["total_gain_loss"]) == Decimal("0")


def test_twr_removes_deposits_and_keeps_fully_sold_symbols_in_history(client):
    headers, portfolio_id, prices = _portfolio_and_prices(client)
    first, middle, last = prices[0], prices[len(prices) // 2], prices[-1]

    def transaction(payload):
        response = client.post(f"/portfolios/{portfolio_id}/transactions", headers=headers, json=payload)
        assert response.status_code == 201, response.text
        return response

    transaction({"transaction_type": "deposit", "amount": "10000", "transaction_date": first.trade_date.isoformat()})
    transaction(
        {
            "symbol": "MEBL",
            "transaction_type": "buy",
            "quantity": "1",
            "price": str(first.close),
            "amount": str(first.close),
            "transaction_date": first.trade_date.isoformat(),
        }
    )
    transaction({"transaction_type": "deposit", "amount": "5000", "transaction_date": middle.trade_date.isoformat()})
    transaction(
        {
            "symbol": "MEBL",
            "transaction_type": "sell",
            "quantity": "1",
            "price": str(last.close),
            "amount": str(last.close),
            "transaction_date": last.trade_date.isoformat(),
        }
    )

    assert client.get(f"/portfolios/{portfolio_id}/positions", headers=headers).json() == []
    points = client.get(f"/portfolios/{portfolio_id}/performance?limit=30", headers=headers).json()
    assert {point["value_date"] for point in points} >= {first.trade_date.isoformat(), last.trade_date.isoformat()}
    middle_point = next(point for point in points if point["value_date"] == middle.trade_date.isoformat())
    assert Decimal(middle_point["external_cash_flow"]) == Decimal("5000")
    assert Decimal(middle_point["day_change"]) == Decimal(middle_point["value_change"]) - Decimal("5000")


def test_transaction_validation_and_snapshot_materialization(client):
    headers, portfolio_id, prices = _portfolio_and_prices(client)
    current = prices[-1]
    mismatched = client.post(
        f"/portfolios/{portfolio_id}/transactions",
        headers=headers,
        json={
            "symbol": "MEBL",
            "transaction_type": "buy",
            "quantity": "10",
            "price": "100",
            "amount": "900",
            "transaction_date": current.trade_date.isoformat(),
        },
    )
    assert mismatched.status_code == 422
    invalid_settlement = client.post(
        f"/portfolios/{portfolio_id}/transactions",
        headers=headers,
        json={
            "symbol": "MEBL",
            "transaction_type": "buy",
            "quantity": "1",
            "price": str(current.close),
            "amount": str(current.close),
            "transaction_date": current.trade_date.isoformat(),
            "settlement_date": "2026-01-01",
        },
    )
    assert invalid_settlement.status_code == 422

    deposit = client.post(
        f"/portfolios/{portfolio_id}/transactions",
        headers=headers,
        json={"transaction_type": "deposit", "amount": "10000", "transaction_date": current.trade_date.isoformat()},
    )
    assert deposit.status_code == 201
    buy = client.post(
        f"/portfolios/{portfolio_id}/transactions",
        headers=headers,
        json={
            "symbol": "MEBL",
            "transaction_type": "buy",
            "quantity": "1",
            "price": str(current.close),
            "amount": str(current.close),
            "transaction_date": current.trade_date.isoformat(),
        },
    )
    assert buy.status_code == 201

    with SessionLocal() as db:
        assert db.scalar(
            select(PortfolioPositionSnapshot).where(
                PortfolioPositionSnapshot.portfolio_id == portfolio_id,
                PortfolioPositionSnapshot.snapshot_date == current.trade_date,
            )
        )
        assert db.scalar(
            select(PortfolioCashSnapshot).where(PortfolioCashSnapshot.snapshot_date == current.trade_date)
        )


def test_stock_split_preserves_total_cost_basis(client):
    headers, portfolio_id, prices = _portfolio_and_prices(client)
    current = prices[-1]
    for payload in (
        {"transaction_type": "deposit", "amount": "10000", "transaction_date": current.trade_date.isoformat()},
        {
            "symbol": "MEBL", "transaction_type": "buy", "quantity": "10", "price": "100",
            "amount": "1000", "transaction_date": current.trade_date.isoformat(),
        },
        {
            "symbol": "MEBL", "transaction_type": "corporate_action", "quantity": "2", "price": "0",
            "amount": "0", "transaction_date": current.trade_date.isoformat(),
        },
    ):
        response = client.post(f"/portfolios/{portfolio_id}/transactions", headers=headers, json=payload)
        assert response.status_code == 201, response.text
    position = client.get(f"/portfolios/{portfolio_id}/positions", headers=headers).json()[0]
    assert Decimal(position["quantity"]) == Decimal("20")
    assert Decimal(position["average_cost"]) == Decimal("50")
    assert Decimal(position["quantity"]) * Decimal(position["average_cost"]) == Decimal("1000")


def test_recorded_corporate_action_is_applied_idempotently(client):
    headers, portfolio_id, prices = _portfolio_and_prices(client)
    current = prices[-1]
    for payload in (
        {"transaction_type": "deposit", "amount": "10000", "transaction_date": current.trade_date.isoformat()},
        {"symbol": "MEBL", "transaction_type": "buy", "quantity": "10", "price": "100", "amount": "1000", "transaction_date": current.trade_date.isoformat()},
    ):
        assert client.post(f"/portfolios/{portfolio_id}/transactions", headers=headers, json=payload).status_code == 201
    action_date = date(2026, 8, 10)
    with SessionLocal() as db:
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        db.add(CorporateAction(instrument_id=instrument.id, action_type="stock_split", effective_date=action_date, details_json='{"split_multiplier": 2}'))
        db.commit()
        first = apply_recorded_corporate_actions(db, action_date)
        second = apply_recorded_corporate_actions(db, action_date)
    assert first["applied"] == 1
    assert second["applied"] == 0
    position = client.get(f"/portfolios/{portfolio_id}/positions", headers=headers).json()[0]
    assert Decimal(position["quantity"]) == Decimal("20")
    assert Decimal(position["average_cost"]) == Decimal("50")
