"""Offline research contracts and fixtures."""

from datetime import UTC, datetime
from decimal import Decimal
from app.core.security import encrypt_secret
from app.models.user import User
from app.models.llm_key import LLMApiKey
from app.models.workstation import (
    Instrument,
    Event,
    EventSource,
    EventEntityLink,
    NormalizedEvent,
    NormalizedEventEvidence,
)
from app.services.rag_service import create_document_from_pages, ParsedPage


def seed(db):
    user = User(email="research@example.test", password_hash="not-a-login-hash")
    other = User(email="other@example.test", password_hash="not-a-login-hash")
    a, b = (
        Instrument(symbol="AAA", name="A", sector="Energy"),
        Instrument(symbol="BBB", name="B", sector="Energy"),
    )
    db.add_all([user, other, a, b])
    db.flush()
    db.add(
        LLMApiKey(
            user_id=user.id,
            provider="gemini",
            encrypted_api_key=encrypt_secret("offline-test-key"),
            masked_api_key="****",
            default_model="offline-test-model",
        )
    )
    norm = NormalizedEvent(
        event_type="earnings",
        classification_status="classified",
        title="Shared quarterly report template",
        occurred_at=datetime.now(UTC),
        cluster_key="shared",
        materiality="medium",
        confidence=1,
        freshness_score=Decimal("0.2"),
        freshness_status="recent",
        detection_version="fixture",
    )
    db.add(norm)
    db.flush()
    for instrument in (a, b):
        doc = create_document_from_pages(
            db,
            [
                ParsedPage(
                    1,
                    "The company announced its quarterly financial results and operating outlook. "
                    * 4,
                )
            ],
            title=instrument.symbol + " report",
            document_type="announcement",
            symbol=instrument.symbol,
            source_name="Pakistan Stock Exchange",
            source_url="https://example.test/" + instrument.symbol,
            data_status="observed",
            commit=False,
        )
        raw = Event(
            event_type="announcement",
            title=instrument.symbol + " quarterly report",
            occurred_at=datetime.now(UTC),
        )
        db.add(raw)
        db.flush()
        db.add_all(
            [
                EventSource(
                    event_id=raw.id,
                    source_name="Pakistan Stock Exchange",
                    source_url=doc.source_url,
                    document_id=doc.id,
                    selection_status="selected",
                ),
                EventEntityLink(
                    event_id=raw.id,
                    entity_type="instrument",
                    entity_key=instrument.symbol,
                    link_method="issuer_metadata",
                    confidence=1,
                ),
                NormalizedEventEvidence(
                    normalized_event_id=norm.id, raw_event_id=raw.id, evidence_role="primary"
                ),
            ]
        )
    db.commit()
    return user, other, a, b
