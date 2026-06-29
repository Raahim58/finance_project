from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import UserResponse
from app.schemas.settings import (
    LLMKeyCreate,
    LLMKeyResponse,
    LLMKeyTest,
    LLMKeyTestResponse,
    PreferencesResponse,
    PreferencesUpdate,
)
from app.services.llm_key_service import create_key, delete_key, list_keys, test_key
from app.services.preferences_service import (
    ensure_preferences,
    serialize_preferences,
    update_preferences,
)

router = APIRouter()


@router.get("/profile", response_model=UserResponse)
def get_profile(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
    )


@router.get("/preferences", response_model=PreferencesResponse)
def get_preferences(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PreferencesResponse:
    return serialize_preferences(ensure_preferences(db, current_user))


@router.patch("/preferences", response_model=PreferencesResponse)
def patch_preferences(
    payload: PreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PreferencesResponse:
    return update_preferences(db, current_user, payload)


@router.get("/llm-keys", response_model=list[LLMKeyResponse])
def get_llm_keys(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[LLMKeyResponse]:
    return list_keys(db, current_user)


@router.post("/llm-keys", response_model=LLMKeyResponse, status_code=status.HTTP_201_CREATED)
async def post_llm_key(
    payload: LLMKeyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LLMKeyResponse:
    return await create_key(db, current_user, payload)


@router.post("/llm-keys/test", response_model=LLMKeyTestResponse)
async def post_llm_key_test(payload: LLMKeyTest) -> LLMKeyTestResponse:
    return await test_key(payload)


@router.delete("/llm-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_llm_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    delete_key(db, current_user, key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
