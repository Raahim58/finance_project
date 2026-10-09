from datetime import date

from app.db.session import SessionLocal
from app.models.portfolio import PortfolioHolding, PortfolioTransaction
from app.models.workstation import AllocationSet
from app.services.market_ingestion import generate_mock_market_data


def _auth(client):
    response = client.post(
        "/auth/signup", json={"email": "intelligence@example.com", "password": "password123"}
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _portfolio(client, headers):
    with SessionLocal() as db:
        generate_mock_market_data(db, days=120, end_date=date(2026, 8, 7))
    portfolio_id = client.post(
        "/portfolios", headers=headers, json={"name": "Intelligence V1"}
    ).json()["id"]
    for symbol, quantity in (("SYS", "10"),):
        response = client.post(
            f"/portfolios/{portfolio_id}/holdings",
            headers=headers,
            json={"symbol": symbol, "quantity": quantity, "average_cost": "100"},
        )
        assert response.status_code == 201
    response = client.post(
        f"/portfolios/{portfolio_id}/ips/confirm",
        headers=headers,
        json={
            "constraints": {
                "max_instrument_weight": 0.70,
                "max_sector_weight": 0.80,
                "min_cash_weight": 0.0,
            }
        },
    )
    assert response.status_code == 201
    return portfolio_id






def test_candidate_evaluation_and_save_never_mutate_ledger(client):
    headers = _auth(client)
    portfolio_id = _portfolio(client, headers)
    with SessionLocal() as db:
        before_holdings = db.query(PortfolioHolding).filter_by(portfolio_id=portfolio_id).count()
        before_transactions = (
            db.query(PortfolioTransaction).filter_by(portfolio_id=portfolio_id).count()
        )
    payload = {
        "portfolio_id": portfolio_id,
        "action": "add",
        "target_weight": 0.05,
        "sizing": "manual",
    }
    response = client.post("/intelligence/securities/MEBL/evaluate", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidate"]["current_weight"] == 0
    assert body["candidate"]["proposed_weight"] == 0.05
    assert body["ledger_mutated"] is False
    assert body["comparison"]["proposed_weights"]["MEBL"] == 0.05
    assert body["stress"]["current"] and body["stress"]["proposed"]
    saved = client.post(
        "/intelligence/securities/MEBL/proposals",
        headers=headers,
        json={**payload, "label": "Review MEBL at 5%"},
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["proposal"]["kind"] == "sandbox"
    assert saved.json()["ledger_mutated"] is False
    with SessionLocal() as db:
        assert (
            db.query(PortfolioHolding).filter_by(portfolio_id=portfolio_id).count()
            == before_holdings
        )
        assert (
            db.query(PortfolioTransaction).filter_by(portfolio_id=portfolio_id).count()
            == before_transactions
        )
        assert (
            db.query(AllocationSet).filter_by(portfolio_id=portfolio_id, kind="sandbox").count()
            == 1
        )


def test_optimizer_candidate_sizing_records_deterministic_objective(client):
    headers = _auth(client)
    portfolio_id = _portfolio(client, headers)
    response = client.post(
        "/intelligence/securities/MEBL/evaluate",
        headers=headers,
        json={"portfolio_id": portfolio_id, "action": "add", "sizing": "optimizer"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["optimizer"]["objective"] == "minimum_variance"
    assert body["candidate"]["proposed_weight"] >= 0
    assert sum(body["comparison"]["proposed_weights"].values()) == 1
