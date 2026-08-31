import json
from datetime import date

import pytest
from sqlalchemy import select

from app.ai.providers.base import LLMProviderResult
from app.db.session import SessionLocal
from app.models.market import Company, Exchange, MarketPrice
from app.models.intelligence_context import IntelligenceContextReceiptRecord
from app.models.workstation import Instrument
from app.services.market_ingestion import generate_mock_market_data
from app.reasoning.contracts import ModelAnswer, ReasoningRequest, RecommendationLabel
from app.reasoning.engine import ReasoningEngine
from app.reasoning.peer_groups import UNCLASSIFIED, build_peer_group_packets
from app.reasoning.validation import validate_model_answer


def _answer(
    *, portfolio_id="p1", instrument_ids=None, evidence_ids=None, recommendation=None
):
    return json.dumps(
        {
            "answer": "Grounded answer.",
            "recommendation": recommendation,
            "confidence": None,
            "horizon": None,
            "portfolio_id": portfolio_id,
            "instrument_ids": instrument_ids or [],
            "evidence_ids": evidence_ids or ["ev:1"],
            "freshness_acknowledgements": [],
        }
    )


class SequenceProvider:
    name = "test"
    default_model = "test-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, _api_key, messages, _model):
        self.calls.append(json.loads(messages[-1]["content"]))
        content = self.responses.pop(0)
        return LLMProviderResult(content=content, provider=self.name, model=self.default_model)


def _request(**updates):
    values = {
        "question": "Analyze this holding",
        "mode": "targeted",
        "portfolio_id": "p1",
        "portfolio_name": "Global portfolio",
        "history": [],
        "grounded_context": {"deterministic_fallback": "Stored grounded facts."},
        "allowed_evidence_ids": {"ev:1"},
        "allowed_instrument_ids": {"i1"},
    }
    values.update(updates)
    return ReasoningRequest(**values)


def test_phase8_numeric_validation_rejects_only_numbers_outside_structured_context():
    request = _request(allowed_numeric_tokens={"12.5", "12.5%"})
    valid = ModelAnswer(
        answer="Observed return was 12.5%.", portfolio_id="p1", evidence_ids=["ev:1"]
    )
    invalid = ModelAnswer(
        answer="Observed return was 99%.", portfolio_id="p1", evidence_ids=["ev:1"]
    )

    assert validate_model_answer(valid, request) == []
    assert "99%" in validate_model_answer(invalid, request)[0]


def test_insufficient_evidence_can_report_a_missing_portfolio_or_horizon():
    answer = ModelAnswer(
        answer="Insufficient evidence: no selected portfolio or mandate is available.",
        recommendation=RecommendationLabel.INSUFFICIENT_EVIDENCE,
        portfolio_id=None,
        evidence_ids=[],
    )

    assert validate_model_answer(answer, _request(portfolio_id=None)) == []


@pytest.mark.asyncio
async def test_phase8_accepts_one_model_authored_answer_without_duplicate_claims():
    provider = SequenceProvider([_answer(instrument_ids=["i1"])])

    result = await ReasoningEngine(provider, "secret", None).run(_request())

    assert result.status == "grounded"
    assert result.answer == "Grounded answer."
    assert result.repaired is False
    assert len(provider.calls) == 1
    assert "claims" not in provider.calls[0]


@pytest.mark.asyncio
async def test_phase8_repairs_mechanical_scope_once_without_changing_labels_itself():
    invalid = _answer(portfolio_id="foreign", instrument_ids=["i1"])
    valid = _answer(instrument_ids=["i1"])
    provider = SequenceProvider([invalid, valid])

    result = await ReasoningEngine(provider, "secret", None).run(_request())

    assert result.status == "grounded"
    assert result.repaired is True
    assert len(provider.calls) == 2
    assert provider.calls[1]["validation_errors"] == [
        "portfolio_id must equal the server-resolved portfolio_id"
    ]


@pytest.mark.asyncio
async def test_phase8_invalid_repair_returns_synthesis_unavailable_without_advisory_label():
    invalid = _answer(portfolio_id="foreign", instrument_ids=["i1"])
    provider = SequenceProvider([invalid, invalid])

    result = await ReasoningEngine(provider, "secret", None).run(_request())

    assert result.status == "unavailable"
    assert result.recommendation is None
    assert result.answer.startswith("Recommendation Synthesis Unavailable")
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_market_graph_maps_every_sector_then_reduces_and_deepens_selected_candidates():
    packets = {
        "Banking": [{"instrument_id": "bank1", "symbol": "BANK", "sector": "Banking"}],
        "Technology": [{"instrument_id": "tech1", "symbol": "TECH", "sector": "Technology"}],
    }
    provider = SequenceProvider(
        [
            json.dumps({"instrument_ids": ["bank1"]}),
            json.dumps({"instrument_ids": ["tech1"]}),
            json.dumps({"instrument_ids": ["bank1", "tech1"]}),
            _answer(instrument_ids=["bank1", "tech1"]),
        ]
    )
    deepened = []

    async def deepen(ids):
        deepened.append(ids)
        return {"allowed_evidence_ids": []}

    result = await ReasoningEngine(provider, "secret", None).run(
        _request(
            question="What stocks should I buy market-wide?",
            mode="market_wide",
            sector_packets=packets,
            allowed_instrument_ids={"bank1", "tech1"},
            deepen_candidates=deepen,
        )
    )

    assert result.status == "grounded"
    assert deepened == [["bank1", "tech1"]]
    sector_calls = [call for call in provider.calls if "sector" in call]
    assert {call["sector"] for call in sector_calls} == {"Banking", "Technology"}
    assert sum(len(call["records"]) for call in sector_calls) == 2


def test_peer_group_assembler_keeps_complete_universe_and_unclassified_members():
    with SessionLocal() as db:
        exchange = Exchange(code="PSX", name="Pakistan Stock Exchange")
        db.add(exchange)
        db.flush()
        companies = [
            Company(symbol="AAA", name="A", sector="Banking", exchange_id=exchange.id),
            Company(symbol="BBB", name="B", sector="Technology", exchange_id=exchange.id),
            Company(symbol="CCC", name="C", sector="Other", exchange_id=exchange.id),
        ]
        db.add_all(companies)
        db.flush()
        instruments = [
            Instrument(company_id=companies[0].id, symbol="AAA", name="A", sector="Banking"),
            Instrument(company_id=companies[1].id, symbol="BBB", name="B", sector="Technology"),
            Instrument(company_id=companies[2].id, symbol="CCC", name="C", sector=None),
        ]
        db.add_all(instruments)
        db.flush()
        for company in companies:
            db.add(
                MarketPrice(
                    company_id=company.id,
                    symbol=company.symbol,
                    trade_date=date(2026, 8, 31),
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    previous_close=100,
                    change=0,
                    change_percent=0,
                    volume=1000,
                    value=100000,
                    source="test",
                )
            )
        db.commit()

        packets = build_peer_group_packets(db, None)

    records = [row for rows in packets.values() for row in rows]
    assert {row["symbol"] for row in records} == {"AAA", "BBB", "CCC"}
    assert len(records) == len({row["instrument_id"] for row in records}) == 3
    assert packets[UNCLASSIFIED][0]["symbol"] == "CCC"
    assert all(row["classification_source"] == "PSX symbol universe" for row in records)


def test_named_comparison_persists_a_receipt_for_each_deep_canonical_context(
    client, monkeypatch
):
    headers = client.post(
        "/auth/signup",
        json={"email": "phase8-comparison@example.com", "password": "password123"},
    ).json()
    auth = {"Authorization": f"Bearer {headers['access_token']}"}
    with SessionLocal() as db:
        generate_mock_market_data(db, days=30, end_date=date(2026, 8, 31))
    portfolio_id = client.post(
        "/portfolios", headers=auth, json={"name": "Global comparison"}
    ).json()["id"]
    for symbol in ("MEBL", "SYS"):
        assert (
            client.post(
                f"/portfolios/{portfolio_id}/holdings",
                headers=auth,
                json={"symbol": symbol, "quantity": "10", "average_cost": "100"},
            ).status_code
            == 201
        )
    assert (
        client.post(
            f"/portfolios/{portfolio_id}/ips/confirm",
            headers=auth,
            json={"constraints": {"max_instrument_weight": 0.8}, "horizon_years": 5},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/settings/llm-keys",
            headers=auth,
            json={"provider": "mock", "api_key": "mock-secret-1234"},
        ).status_code
        == 201
    )

    class ComparisonProvider:
        name = "test"
        default_model = "test"

        async def chat(self, _api_key, messages, _model):
            payload = json.loads(messages[-1]["content"])
            return LLMProviderResult(
                content=json.dumps(
                    {
                        "answer": "MEBL and SYS were compared using the supplied contexts.",
                        "recommendation": None,
                        "confidence": None,
                        "horizon": None,
                        "portfolio_id": payload["portfolio_id"],
                        "instrument_ids": payload["selected_instrument_ids"],
                        "evidence_ids": [payload["allowed_evidence_ids"][0]],
                        "freshness_acknowledgements": ["Freshness warnings acknowledged."],
                    }
                ),
                provider="test",
                model="test",
            )

    monkeypatch.setattr(
        "app.ai.orchestrator.get_provider", lambda _name: ComparisonProvider()
    )
    response = client.post(
        "/assistant/messages",
        headers=auth,
        json={
            "question": "Compare MEBL and SYS for my portfolio",
            "provider": "mock",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["synthesis"]["mode"] == "llm_grounded"
    receipt_ids = body["synthesis"]["context_receipt_ids"]
    assert len(receipt_ids) == 2
    with SessionLocal() as db:
        receipts = list(
            db.scalars(
                select(IntelligenceContextReceiptRecord).where(
                    IntelligenceContextReceiptRecord.id.in_(receipt_ids)
                )
            )
        )
    assert len(receipts) == 2
    assert {receipt.consumer_key for receipt in receipts} == {body["conversation_id"]}
    assert body["message_id"] in {receipt.output_id for receipt in receipts}
