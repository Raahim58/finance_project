import pytest


@pytest.fixture(autouse=True)
def offline_token_preflight(monkeypatch):
    # Existing provider fixtures mock generation. Counting is a separate endpoint
    # and must never leak fixture/user context to a real API during the suite.
    from app.ai.providers.http_placeholders import AnthropicProvider

    original = AnthropicProvider.count_input_tokens

    async def unavailable(*_args):
        raise RuntimeError("Offline token count not explicitly mocked")

    monkeypatch.setattr(AnthropicProvider, "count_input_tokens", unavailable)
    return original


@pytest.fixture
def token_count_transport(monkeypatch, offline_token_preflight):
    """Opt in to the count adapter only in tests supplying a mocked HTTP transport."""
    from app.ai.providers.http_placeholders import AnthropicProvider

    monkeypatch.setattr(AnthropicProvider, "count_input_tokens", offline_token_preflight)


@pytest.fixture(autouse=True)
def route_classifier_off_by_default(monkeypatch):
    # Canned-provider tests count model calls; the classifier has its own tests.
    from app.core.config import settings

    monkeypatch.setattr(settings, "assistant_route_classifier_enabled", False)


@pytest.fixture
def route_classifier_enabled(monkeypatch, route_classifier_off_by_default):
    from app.core.config import settings

    monkeypatch.setattr(settings, "assistant_route_classifier_enabled", True)


@pytest.fixture
def database():
    """Fresh application schema only for tests explicitly requiring stored state."""
    # Importing the application registers all models before creating the schema.
    from app.main import app  # noqa: F401
    from app.db.session import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(database):
    from fastapi.testclient import TestClient
    from app.main import app

    # Preserve the existing no-lifespan API fixture; lifecycle has dedicated tests.
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
