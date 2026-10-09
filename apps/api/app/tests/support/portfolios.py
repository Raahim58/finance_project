"""Offline portfolios contracts and fixtures."""

from datetime import date
from app.db.session import SessionLocal
from app.services.market_ingestion import generate_mock_market_data
from app.tests.support.users import signup_user


def signup(client, email="workstation@example.com"):
    return signup_user(client, email)


def seeded_portfolio(client, headers):
    with SessionLocal() as db:
        generate_mock_market_data(db, days=90, end_date=date(2026, 8, 7))
    portfolio_id = client.post("/portfolios", headers=headers, json={"name": "Quant"}).json()["id"]
    for symbol, quantity in [("MEBL", "10"), ("SYS", "5")]:
        response = client.post(
            f"/portfolios/{portfolio_id}/holdings",
            headers=headers,
            json={"symbol": symbol, "quantity": quantity, "average_cost": "100"},
        )
        assert response.status_code == 201
    return portfolio_id


def _as_user(db, client, headers):
    from app.models.user import User

    return db.get(User, client.get("/auth/me", headers=headers).json()["id"])


def positions(client, headers, portfolio_id):
    from app.services.portfolio_service import get_positions

    with SessionLocal() as db:
        return [row.model_dump(mode="json") for row in get_positions(db, _as_user(db, client, headers), portfolio_id)]


def cash(client, headers, portfolio_id):
    from app.services.portfolio_service import get_cash

    with SessionLocal() as db:
        return get_cash(db, _as_user(db, client, headers), portfolio_id).model_dump(mode="json")


def restore(client, headers, portfolio_id):
    from app.services.portfolio_service import restore_portfolio

    with SessionLocal() as db:
        return restore_portfolio(db, _as_user(db, client, headers), portfolio_id).model_dump(mode="json")


def update_holding(client, headers, holding_id, **fields):
    from app.schemas.portfolio import HoldingUpdate
    from app.services.portfolio_service import update_holding as run

    with SessionLocal() as db:
        return run(db, _as_user(db, client, headers), holding_id, HoldingUpdate(**fields)).model_dump(mode="json")


def update_transaction(client, headers, transaction_id, **fields):
    from app.schemas.portfolio import TransactionUpdate
    from app.services.portfolio_service import update_transaction as run

    with SessionLocal() as db:
        return run(db, _as_user(db, client, headers), transaction_id, TransactionUpdate(**fields)).model_dump(mode="json")


def delete_holding(client, headers, holding_id):
    from app.services.portfolio_service import delete_holding as run

    with SessionLocal() as db:
        run(db, _as_user(db, client, headers), holding_id)


def delete_transaction(client, headers, transaction_id):
    from app.services.portfolio_service import delete_transaction as run

    with SessionLocal() as db:
        run(db, _as_user(db, client, headers), transaction_id)


def ingest_text(client, headers, json):
    """Stored-text ingestion through the service (the HTTP route was removed)."""
    from types import SimpleNamespace

    from app.schemas.rag import DocumentIngestRequest
    from app.services.rag_service import ingest_text_document

    with SessionLocal() as db:
        body = ingest_text_document(db, _as_user(db, client, headers), DocumentIngestRequest(**json)).model_dump(mode="json")
    return SimpleNamespace(status_code=201, json=lambda: body)
