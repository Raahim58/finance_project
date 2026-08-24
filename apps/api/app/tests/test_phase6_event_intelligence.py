from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json

import pytest
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.domain.event_intelligence import classify_event, event_materiality
from app.models.workstation import (
    Event,
    EventEntityLink,
    EventSource,
    Instrument,
    NormalizedEvent,
    NormalizedEventEvidence,
    NormalizedEventSubject,
)
from app.services.event_intelligence_service import normalize_raw_event
from app.services.market_ingestion import generate_mock_market_data


NOW = datetime.now(UTC).replace(microsecond=0)


def _seed_market() -> None:
    with SessionLocal() as db:
        generate_mock_market_data(db, days=3, end_date=date.today())


def _raw_event(
    *,
    title: str,
    raw_type: str = "announcement",
    symbol: str | None = None,
    source_name: str = "Pakistan Stock Exchange",
    source_url: str | None = None,
    occurred_at: datetime = NOW,
) -> str:
    with SessionLocal() as db:
        event = Event(
            event_type=raw_type,
            title=title,
            occurred_at=occurred_at,
            event_time_end=occurred_at,
            geography="PK",
            details_json=(f'{{"official_entity_key":"{symbol}"}}' if symbol else "{}"),
        )
        db.add(event)
        db.flush()
        db.add(EventSource(
            event_id=event.id,
            source_url=source_url or f"https://example.test/{event.id}",
            source_name=source_name,
            published_at=occurred_at,
            selection_status="selected",
        ))
        if symbol:
            db.add(EventEntityLink(
                event_id=event.id,
                entity_type="instrument",
                entity_key=symbol,
                link_method="exact_alias",
                confidence=Decimal("1"),
            ))
        db.commit()
        return event.id


def _auth(client):
    response = client.post(
        "/auth/signup",
        json={"email": "phase6@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_deterministic_rules_classify_rates_and_materiality_without_llm():
    detection = classify_event("SBP raises the policy rate by 100 basis points")
    assert detection.event_type == "rates"
    assert detection.factor == "interest_rates"
    assert detection.magnitude is not None
    assert detection.magnitude.value == Decimal("100")
    assert detection.magnitude.unit == "bps"
    assert detection.magnitude.direction == "increase"
    assert event_materiality(detection, "policy rate raised 100 basis points", has_direct_subject=False) == "high"


@pytest.mark.parametrize(
    ("text", "expected_type"),
    [
        ("quarterly financial results announced", "earnings"),
        ("credit of interim cash dividend", "dividend"),
        ("company approves a rights issue", "corporate_action"),
        ("production suspended after plant fire", "operational_disruption"),
        ("SECP regulatory order issued", "regulation"),
        ("SBP monetary policy rate decision", "rates"),
        ("rupee depreciation changes the exchange rate", "fx"),
        ("new oil discovery starts production", "oil_commodities"),
        ("trade sanctions follow geopolitical tensions", "geopolitical_risk"),
    ],
)
def test_controlled_taxonomy_is_phrase_rule_driven(text, expected_type):
    assert classify_event(text).event_type == expected_type


def test_normalization_preserves_raw_evidence_and_direct_issuer_subject():
    _seed_market()
    raw_id = _raw_event(
        title="MEBL declares 80 percent interim cash dividend",
        symbol="MEBL",
        source_url="https://dps.psx.com.pk/notice/80",
    )
    with SessionLocal() as db:
        normalized = normalize_raw_event(db, raw_id)
        subjects = list(db.scalars(select(NormalizedEventSubject).where(
            NormalizedEventSubject.normalized_event_id == normalized.id
        )))
        link = db.scalar(select(NormalizedEventEvidence).where(
            NormalizedEventEvidence.raw_event_id == raw_id
        ))

        assert normalized.event_type == "dividend"
        assert normalized.materiality == "high"
        assert normalized.magnitude == Decimal("80")
        assert normalized.magnitude_unit == "percent"
        assert normalized.classification_status == "classified"
        assert any(
            row.subject_type == "instrument"
            and row.subject_key == "MEBL"
            and row.link_method == "issuer_metadata"
            and row.is_direct
            for row in subjects
        )
        assert any(row.subject_type == "sector" and not row.is_direct for row in subjects)
        assert link is not None and link.evidence_role == "primary"
        assert db.get(Event, raw_id).event_type == "announcement"


def test_duplicate_coverage_clusters_and_preserves_both_sources():
    _seed_market()
    first_id = _raw_event(
        title="MEBL declares 80 percent interim cash dividend",
        symbol="MEBL",
        source_url="https://dps.psx.com.pk/notice/80",
    )
    second_id = _raw_event(
        title="Meezan Bank announces 80 percent interim cash dividend",
        raw_type="news",
        symbol="MEBL",
        source_name="Business Recorder",
        source_url="https://business-recorder.test/mebl-dividend",
        occurred_at=NOW + timedelta(hours=2),
    )
    with SessionLocal() as db:
        first = normalize_raw_event(db, first_id)
        second = normalize_raw_event(db, second_id)
        evidence_count = db.scalar(select(func.count()).select_from(NormalizedEventEvidence).where(
            NormalizedEventEvidence.normalized_event_id == first.id
        ))
        assert second.id == first.id
        assert evidence_count == 2
        assert db.scalar(select(func.count()).select_from(EventSource)) == 2
        assert json.loads(second.details_json)["independent_source_count"] == 2
        roles = set(db.scalars(select(NormalizedEventEvidence.evidence_role)))
        assert roles == {"primary", "corroborating"}


def test_unsupported_item_remains_unclassified_and_does_not_invent_impact():
    raw_id = _raw_event(title="Notice of postal ballot availability", symbol=None)
    with SessionLocal() as db:
        normalized = normalize_raw_event(db, raw_id)
        details = normalized.details_json
        assert normalized.event_type == "unclassified"
        assert normalized.classification_status == "unclassified"
        assert normalized.materiality == "unknown"
        assert '"impact_interpretation": "not_calculated"' in details


def test_prototype_similarity_cannot_publish_an_event(monkeypatch):
    raw_id = _raw_event(title="Notice of postal ballot availability")
    monkeypatch.setattr(
        "app.services.event_intelligence_service._prototype_match",
        lambda _text: ("earnings", 0.99),
    )
    with SessionLocal() as db:
        normalized = normalize_raw_event(db, raw_id)
        assert normalized.classification_status == "unclassified"
        assert normalized.event_type == "unclassified"


def test_synthetic_event_is_not_normalized_as_observed():
    with SessionLocal() as db:
        event = Event(
            event_type="news",
            title="Synthetic demo financial results",
            occurred_at=NOW,
            details_json='{"data_classification":"synthetic_demo"}',
        )
        db.add(event)
        db.flush()
        db.add(EventSource(
            event_id=event.id,
            source_url="demo://event/1",
            source_name="Deterministic Demo Seed",
        ))
        db.commit()
        event_id = event.id
    with SessionLocal() as db, pytest.raises(ValueError, match="Synthetic/demo"):
        normalize_raw_event(db, event_id)


def test_company_and_portfolio_apis_surface_only_direct_subjects_with_exact_weight(client):
    _seed_market()
    raw_id = _raw_event(
        title="MEBL declares 80 percent interim cash dividend",
        symbol="MEBL",
        source_url="https://dps.psx.com.pk/notice/80",
    )
    with SessionLocal() as db:
        normalize_raw_event(db, raw_id)
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        assert instrument is not None
        instrument_id = instrument.id

    headers = _auth(client)
    company = client.get(
        f"/companies/{instrument_id}/intelligence-events", headers=headers
    )
    assert company.status_code == 200
    assert [row["event_type"] for row in company.json()] == ["dividend"]
    assert company.json()[0]["impact"]["status"] == "not_calculated"

    portfolio_id = client.post("/portfolios", headers=headers, json={"name": "Event portfolio"}).json()["id"]
    holding = client.post(
        f"/portfolios/{portfolio_id}/holdings",
        headers=headers,
        json={"symbol": "MEBL", "quantity": "10", "average_cost": "100"},
    )
    assert holding.status_code == 201
    response = client.get(f"/portfolios/{portfolio_id}/events", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["holdings"] == [
        {"symbol": "MEBL", "current_portfolio_weight": 1.0}
    ]
    assert body["events"][0]["affected_portfolio_weight"] == 1.0
    assert body["events"][0]["impact_direction"] is None
    assert "not_implemented" in body["events"][0]["impact_calculation"]


def test_sector_subject_alone_never_becomes_direct_company_event(client):
    _seed_market()
    raw_id = _raw_event(title="Oil price rises 5 percent", raw_type="news")
    with SessionLocal() as db:
        normalized = normalize_raw_event(db, raw_id)
        db.add(NormalizedEventSubject(
            normalized_event_id=normalized.id,
            subject_type="sector",
            subject_key="Commercial Banks",
            link_method="factor_sector_mapping",
            confidence=Decimal("0.7"),
            is_direct=False,
        ))
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "MEBL"))
        db.commit()
        instrument_id = instrument.id

    response = client.get(
        f"/companies/{instrument_id}/intelligence-events", headers=_auth(client)
    )
    assert response.status_code == 200
    assert response.json() == []
