from datetime import date, timedelta

import pytest
from pydantic import BaseModel

from app.tools.market_tools import MarketSeriesInput, _series
from app.tools.registry import ToolDefinition, ToolRegistry


class EmptyInput(BaseModel):
    pass


def _definition(*, name: str = "test.tool", timeout: int = 5, cost: str = "low", confirmation: bool = False):
    return ToolDefinition(
        name=name,
        version="1.0",
        description="test",
        input_model=EmptyInput,
        permission_scope="test:read",
        read_only=True,
        requires_confirmation=confirmation,
        timeout_seconds=timeout,
        cost_class=cost,
        handler=lambda _db, _user, _payload: {"ok": True},
    )


def test_tool_registry_enforces_cost_and_confirmation_budgets():
    registry = ToolRegistry()
    registry.register(_definition(name="test.low"))
    registry.register(_definition(name="test.confirm", confirmation=True))

    assert registry.invoke("test.low", None, None, {}, max_cost_units=1) == {"ok": True}
    with pytest.raises(PermissionError, match="cost budget"):
        registry.invoke("test.low", None, None, {}, max_cost_units=1)
    with pytest.raises(PermissionError, match="explicit confirmation"):
        registry.invoke("test.confirm", None, None, {}, confirmed=False)


def test_sync_registry_does_not_claim_post_return_timeout_cancellation(monkeypatch):
    ticks = iter([10.0, 12.0])
    monkeypatch.setattr("app.tools.registry.monotonic", lambda: next(ticks))
    registry = ToolRegistry()
    registry.register(_definition(timeout=1))

    assert registry.invoke("test.tool", None, None, {}) == {"ok": True}


def test_market_series_bounds_model_payload_and_returns_older_history_cursor(monkeypatch):
    first = date(2025, 1, 1)
    rows = [
        {
            "date": first + timedelta(days=index),
            "close": index,
            "source": "fixture",
            "source_url": "https://example.test/series",
            "artifact_id": "artifact-1",
            "artifact_sha256": "sha-1",
        }
        for index in range(300)
    ]
    monkeypatch.setattr(
        "app.tools.market_tools.market_series",
        lambda *_args: {"instrument_id": "instrument-1", "symbol": "TEST", "series": rows},
    )

    result = _series(None, None, MarketSeriesInput(instrument_id="instrument-1"))

    assert result["coverage"]["returned"] == 260
    assert result["coverage"]["remaining"] == 40
    assert result["coverage"]["continuation"] == (first + timedelta(days=39)).isoformat()
    assert len(result["data"]["series"]["rows"]) == 260


def test_market_series_accepts_single_latest_row(monkeypatch):
    rows = [
        {"date": date(2026, 8, 11), "close": 100, "source": "fixture"},
        {"date": date(2026, 8, 12), "close": 101, "source": "fixture"},
    ]
    monkeypatch.setattr(
        "app.tools.market_tools.market_series",
        lambda *_args: {"instrument_id": "instrument-1", "symbol": "TEST", "series": rows},
    )

    result = _series(
        None,
        None,
        MarketSeriesInput(instrument_id="instrument-1", limit=1),
    )

    assert result["coverage"]["returned"] == 1
    assert result["data"]["series"]["rows"] == [
        [date(2026, 8, 12), 101, "market_source_1"]
    ]
