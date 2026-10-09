"""Offline assistant contracts and fixtures."""

import json
from datetime import date
from cryptography.fernet import Fernet
from sqlalchemy import select
from app.core.config import settings
from app.core.security import encrypt_secret
from app.db.session import SessionLocal
from app.models.llm_key import LLMApiKey
from app.models.user import User
from app.models.workstation import Instrument
from app.services.market_ingestion import generate_mock_market_data
from uuid import uuid4
from app.schemas.assistant import AssistantMessageCreate
from app.services import assistant_execution
from app.tests.support.users import signup_user


def _anthropic_tool_results(payload):
    # Native associations stay present; fused values live in the current packet.
    from app.ai.company_packet import PACKET_PREFIX, PACKET_SECTIONS
    from app.tools.registry import expand_model_data

    packet = None
    for message in payload["messages"]:
        for block in message.get("content", []) if isinstance(message.get("content"), list) else []:
            if block.get("type") == "text" and block.get("text", "").startswith(PACKET_PREFIX):
                packet = expand_model_data(json.loads(block["text"][len(PACKET_PREFIX) :]))
    for message in reversed(payload["messages"]):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        results = [block for block in content if block.get("type") == "tool_result"]
        if not results:
            continue
        output = []
        for block in results:
            result = json.loads(block["content"])
            if result.get("evidence_location"):
                native = next(
                    tool
                    for msg in payload["messages"]
                    for tool in (
                        msg.get("content", []) if isinstance(msg.get("content"), list) else []
                    )
                    if tool.get("type") == "tool_use" and tool["id"] == block["tool_use_id"]
                )
                scope = {
                    k: v
                    for k, v in native["input"].items()
                    if k not in ("cursor", "limit", "sector_comparison_limit")
                }
                result = next(
                    section
                    for key in PACKET_SECTIONS
                    for section in packet[key]
                    if section["tool"] == native["name"].replace("__", ".")
                    and section["scope"] == scope
                )
            output.append(result)
        return output
    return []


def _mock_market(monkeypatch):
    monkeypatch.setattr(settings, "market_data_mode", "mock")
    with SessionLocal() as db:
        generate_mock_market_data(db, days=40, end_date=date(2026, 8, 7))
        rows = list(db.scalars(select(Instrument).order_by(Instrument.symbol)))
        return rows


def auth_with_provider(client, monkeypatch, *, provider, model, email):
    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    headers = signup(client, email)
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == email))
        user.preferences.default_llm_provider = provider
        db.add(
            LLMApiKey(
                user_id=user.id,
                provider=provider,
                encrypted_api_key=encrypt_secret(f"offline-{provider}-key"),
                masked_api_key="offlin...-key",
                default_model=model,
            )
        )
        return headers, user.id


def _auth_with_anthropic(client, monkeypatch, email="phase2@example.com"):
    return auth_with_provider(
        client, monkeypatch, provider="anthropic", model="claude-test", email=email
    )


def _auth_with_gemini(client, monkeypatch, email="phase2-gemini@example.com"):
    return auth_with_provider(
        client, monkeypatch, provider="gemini", model="gemini-3-flash-preview", email=email
    )


def signup(client, email="phase11@example.com"):
    return signup_user(client, email)


def accepted(client, question="First question"):
    headers = signup(client)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "phase11@example.com"))
        run = assistant_execution.accept(
            db, user, AssistantMessageCreate(question=question), str(uuid4())
        )
        return headers, user.id, run.id, run.conversation_id


_OMITTED_USAGE = object()


def anthropic_turn(content, *, identifier, stop_reason="end_turn", model="claude-test", usage=_OMITTED_USAGE):
    """Native response envelope; each test supplies its own content and identity."""
    return {
        "id": identifier,
        "model": model,
        "stop_reason": stop_reason,
        "content": content,
        "usage": {} if usage is _OMITTED_USAGE else usage,
    }


def anthropic_text(text, **options):
    return anthropic_turn([{"type": "text", "text": text}], **options)
