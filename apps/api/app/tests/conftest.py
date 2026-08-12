import os

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["APP_ENV"] = "test"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["ENABLE_DEMO_ACCESS"] = "false"
os.environ["DEMO_ACCESS_TOKEN"] = ""
os.environ["MARKET_DATA_MODE"] = "mock"
os.environ["MARKET_DATA_DEFAULT_SYMBOLS"] = ""
os.environ["MARKET_HISTORY_BOOTSTRAP_ENABLED"] = "false"
os.environ["SCHEDULED_RESEARCH_ENABLED"] = "false"
os.environ["EMBEDDING_BACKEND"] = "hash"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret"
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode("utf-8")

import pytest
from fastapi.testclient import TestClient

from app.db.session import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
