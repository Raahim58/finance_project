"""Offline tools contracts and fixtures."""

from sqlalchemy import func, select
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.intelligence_context import ContextRefreshRequest
from app.models.portfolio import PortfolioTransaction
from app.models.user import User
from app.models.workstation import AllocationSet
from app.seed.demo import seed_workstation


def _seed(monkeypatch):
    monkeypatch.setenv("DEMO_USER_PASSWORD", "local-test-password")
    result = seed_workstation(include_mock_world=True)
    with SessionLocal() as db:
        return result, db.scalar(select(User).where(User.email == result["user_email"])).id


def _counts(db):
    return {
        "transactions": db.scalar(select(func.count()).select_from(PortfolioTransaction)),
        "allocations": db.scalar(select(func.count()).select_from(AllocationSet)),
        "documents": db.scalar(select(func.count()).select_from(Document)),
        "refreshes": db.scalar(select(func.count()).select_from(ContextRefreshRequest)),
    }


def base64_decode(value):
    import base64

    return base64.b64decode(value)
