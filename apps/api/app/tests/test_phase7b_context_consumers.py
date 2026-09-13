from datetime import date

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.intelligence_context import (
    ContextIngestionWork,
    ContextRefreshRequest,
    IntelligenceContextReceiptRecord,
)
from app.models.user import User
from app.models.workstation import Instrument, StandardizedFinancialFact
from app.services.market_ingestion import generate_mock_market_data
from app.services.context_refresh_service import reconcile_pending_contexts


def _auth(client, email: str):
    response = client.post("/auth/signup", json={"email": email, "password": "password123"})
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _instrument_and_fact() -> str:
    with SessionLocal() as db:
        generate_mock_market_data(db, days=120, end_date=date(2026, 8, 7))
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        db.add(
            StandardizedFinancialFact(
                instrument_id=instrument.id,
                metric="revenue",
                period_type="annual",
                period_key="2025",
                period_end=date(2025, 12, 31),
                value=100,
                unit="PKR",
                currency="PKR",
                source="dps",
                source_url="https://dps.psx.com.pk/company/MEBL",
                quality_status="observed",
            )
        )
        db.commit()
        return instrument.id


def _portfolio(client, headers, name: str, *, confirm_ips: bool = True) -> str:
    portfolio_id = client.post("/portfolios", headers=headers, json={"name": name}).json()["id"]
    assert (
        client.post(
            f"/portfolios/{portfolio_id}/holdings",
            headers=headers,
            json={"symbol": "MEBL", "quantity": "10", "average_cost": "100"},
        ).status_code
        == 201
    )
    if confirm_ips:
        response = client.post(
            f"/portfolios/{portfolio_id}/ips/confirm",
            headers=headers,
            json={
                "constraints": {
                    "max_instrument_weight": 0.7,
                    "max_sector_weight": 0.8,
                    "min_cash_weight": 0,
                },
                "horizon_years": 5,
            },
        )
        assert response.status_code == 201
    return portfolio_id


def test_company_research_uses_company_only_canonical_contract_and_persists_receipt(client):
    headers = _auth(client, "phase7b-company@example.com")
    instrument_id = _instrument_and_fact()

    response = client.get(f"/companies/{instrument_id}/overview", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["context_contract_version"] == "7a.v1"
    assert body["context"]["scope"] == "company_intelligence"
    assert "portfolio" not in body["context"]["sections"]
    assert "ips" not in body["context"]["sections"]
    assert body["context_receipt"]["content_hash"]
    with SessionLocal() as db:
        receipt = db.get(IntelligenceContextReceiptRecord, body["context_receipt_id"])
        assert receipt.consumer_type == "company_research"
        assert receipt.consumer_key == f"instrument:{instrument_id}:portfolio:none"


def test_company_view_can_deactivate_refresh_for_lazy_rebuild(client):
    headers = _auth(client, "phase7b-inactive@example.com")
    instrument_id = _instrument_and_fact()
    body = client.get(f"/companies/{instrument_id}/overview", headers=headers).json()
    refresh_id = body["refresh_request_id"]
    assert refresh_id

    response = client.post(
        f"/research/context-refreshes/{refresh_id}/deactivate", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["active"] is False
    with SessionLocal() as db:
        assert db.get(ContextRefreshRequest, refresh_id).active is False


def test_active_company_view_returns_rebuilt_canonical_result(client):
    headers = _auth(client, "phase7b-active-company@example.com")
    instrument_id = _instrument_and_fact()
    initial = client.get(f"/companies/{instrument_id}/overview", headers=headers).json()
    refresh_id = initial["refresh_request_id"]
    assert refresh_id

    with SessionLocal() as db:
        for work in db.scalars(select(ContextIngestionWork)):
            work.status = "succeeded"
        db.commit()
        sweep = reconcile_pending_contexts(db)
        assert sweep.rebuilt == 1

    refreshed = client.get(
        f"/research/context-refreshes/{refresh_id}", headers=headers
    )
    assert refreshed.status_code == 200
    body = refreshed.json()
    assert body["status"] == "rebuilt"
    assert body["result"]["context_contract_version"] == "7a.v1"
    assert body["result"]["context_receipt_id"] != initial["context_receipt_id"]
    assert body["result"]["context"]["scope"] == "company_intelligence"


def test_company_research_switches_exactly_one_portfolio_and_reuses_company_evidence(client):
    headers = _auth(client, "phase7b-switch@example.com")
    instrument_id = _instrument_and_fact()
    first = _portfolio(client, headers, "First mandate")
    second = _portfolio(client, headers, "Second mandate")

    one = client.get(
        f"/companies/{instrument_id}/overview?portfolio_id={first}", headers=headers
    ).json()["context"]
    two = client.get(
        f"/companies/{instrument_id}/overview?portfolio_id={second}", headers=headers
    ).json()["context"]

    assert one["scope"] == two["scope"] == "portfolio_relevance"
    assert one["sections"]["portfolio"]["data"]["id"] == first
    assert two["sections"]["portfolio"]["data"]["id"] == second
    assert one["sections"]["ips"]["data"]["portfolio_id"] == first
    assert two["sections"]["ips"]["data"]["portfolio_id"] == second
    assert [row["evidence_id"] for row in one["sections"]["company_facts"]["evidence"]] == [
        row["evidence_id"] for row in two["sections"]["company_facts"]["evidence"]
    ]
    assert two["sections"]["company_facts"]["reused"] is True


def test_company_research_rejects_another_users_portfolio_before_persisting_receipt(client):
    owner = _auth(client, "phase7b-owner@example.com")
    intruder = _auth(client, "phase7b-intruder@example.com")
    instrument_id = _instrument_and_fact()
    portfolio_id = _portfolio(client, owner, "Private mandate")

    response = client.get(
        f"/companies/{instrument_id}/overview?portfolio_id={portfolio_id}",
        headers=intruder,
    )

    assert response.status_code == 404
    with SessionLocal() as db:
        intruder_user = db.scalar(select(User).where(User.email == "phase7b-intruder@example.com"))
        assert (
            db.scalar(
                select(IntelligenceContextReceiptRecord).where(
                    IntelligenceContextReceiptRecord.user_id == intruder_user.id
                )
            )
            is None
        )
