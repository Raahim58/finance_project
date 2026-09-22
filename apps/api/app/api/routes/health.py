from fastapi import APIRouter, HTTPException
from redis import Redis
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.ingestion.artifact_store import get_artifact_store

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict[str, object]:
    checks: dict[str, str] = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
        redis = Redis.from_url(settings.celery_broker_url, socket_connect_timeout=2, socket_timeout=2)
        redis.ping()
        checks["redis"] = "ok"
        get_artifact_store(settings).check()
        checks["artifacts"] = "ok"
    except Exception as exc:
        # Report the dependency class, never credentials or connection URLs.
        if "database" not in checks:
            failed = "database"
        elif "redis" not in checks:
            failed = "redis"
        else:
            failed = "artifacts"
        checks[failed] = f"error:{type(exc).__name__}"
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks}) from exc
    return {"status": "ready", "checks": checks}
