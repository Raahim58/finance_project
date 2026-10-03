import os

import pytest
from fastapi.testclient import TestClient

# Unit/integration tests use the explicitly labelled deterministic fallback so
# the suite remains offline. Production and local app defaults use MiniLM.
os.environ.setdefault("EMBEDDING_BACKEND", "hash")

from app.db.session import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def offline_token_preflight(monkeypatch, request):
    # Existing provider fixtures mock generation. Counting is a separate endpoint
    # and must never leak fixture/user context to a real API during the suite.
    if request.path.name != "test_token_counting.py":
        from app.ai.providers.http_placeholders import AnthropicProvider
        async def unavailable(*_args):
            raise RuntimeError("Offline token count not explicitly mocked")
        monkeypatch.setattr(AnthropicProvider, "count_input_tokens", unavailable)


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
