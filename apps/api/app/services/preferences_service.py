import json

from sqlalchemy.orm import Session

from app.models.user import User, UserPreferences
from app.schemas.settings import PreferencesResponse, PreferencesUpdate


def ensure_preferences(db: Session, user: User) -> UserPreferences:
    if user.preferences:
        return user.preferences
    user.preferences = UserPreferences(user_id=user.id)
    db.add(user.preferences)
    db.commit()
    db.refresh(user.preferences)
    return user.preferences


def serialize_preferences(preferences: UserPreferences) -> PreferencesResponse:
    return PreferencesResponse(
        default_llm_provider=preferences.default_llm_provider,
        risk_tolerance=preferences.risk_tolerance,
        investment_horizon=preferences.investment_horizon,
        preferred_analysis_mode=preferences.preferred_analysis_mode,
        preferred_sectors=json.loads(preferences.preferred_sectors),
        avoided_sectors=json.loads(preferences.avoided_sectors),
        notification_preferences=json.loads(preferences.notification_preferences),
        followup_frequency=preferences.followup_frequency,
    )


def update_preferences(
    db: Session, user: User, payload: PreferencesUpdate
) -> PreferencesResponse:
    preferences = ensure_preferences(db, user)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if value is None:
            continue
        if key in {"preferred_sectors", "avoided_sectors", "notification_preferences"}:
            setattr(preferences, key, json.dumps(value))
        else:
            setattr(preferences, key, value)
    db.add(preferences)
    db.commit()
    db.refresh(preferences)
    return serialize_preferences(preferences)
