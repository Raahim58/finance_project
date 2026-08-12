from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers.registry import get_provider
from app.core.security import decrypt_secret, encrypt_secret, mask_api_key
from app.models.llm_key import LLMApiKey
from app.models.user import User, UserPreferences
from app.schemas.settings import LLMKeyCreate, LLMKeyResponse, LLMKeyTest, LLMKeyTestResponse


def serialize_key(key: LLMApiKey) -> LLMKeyResponse:
    return LLMKeyResponse(
        id=key.id,
        provider=key.provider,
        masked_api_key=key.masked_api_key,
        default_model=key.default_model,
        is_active=key.is_active,
        last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
    )


def list_keys(db: Session, user: User) -> list[LLMKeyResponse]:
    rows = db.scalars(
        select(LLMApiKey).where(LLMApiKey.user_id == user.id).order_by(LLMApiKey.created_at.desc())
    ).all()
    return [serialize_key(row) for row in rows]


async def test_key(payload: LLMKeyTest) -> LLMKeyTestResponse:
    try:
        provider = get_provider(payload.provider)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    valid = await provider.validate_key(payload.api_key)
    return LLMKeyTestResponse(
        provider=provider.name,
        valid=valid,
        message="Key format accepted" if valid else "Key was rejected by provider validation",
    )


async def create_key(db: Session, user: User, payload: LLMKeyCreate) -> LLMKeyResponse:
    try:
        provider = get_provider(payload.provider)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    valid = await provider.validate_key(payload.api_key)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API key validation failed")

    key = LLMApiKey(
        user_id=user.id,
        provider=provider.name,
        encrypted_api_key=encrypt_secret(payload.api_key),
        masked_api_key=mask_api_key(payload.api_key),
        default_model=payload.default_model or provider.default_model,
    )
    db.add(key)
    preferences = user.preferences
    if preferences is None:
        preferences = UserPreferences(user_id=user.id)
        db.add(preferences)
    preferences.default_llm_provider = provider.name
    db.commit()
    db.refresh(key)
    return serialize_key(key)


def delete_key(db: Session, user: User, key_id: str) -> None:
    key = db.get(LLMApiKey, key_id)
    if not key or key.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LLM key not found")
    db.delete(key)
    db.commit()


def get_decrypted_key_for_call(db: Session, user: User, provider_name: str) -> tuple[str, LLMApiKey]:
    key = db.scalar(
        select(LLMApiKey)
        .where(
            LLMApiKey.user_id == user.id,
            LLMApiKey.provider == provider_name.lower(),
            LLMApiKey.is_active.is_(True),
        )
        .order_by(LLMApiKey.created_at.desc())
    )
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active key for provider")
    key.last_used_at = datetime.now(UTC)
    db.add(key)
    db.commit()
    return decrypt_secret(key.encrypted_api_key), key
