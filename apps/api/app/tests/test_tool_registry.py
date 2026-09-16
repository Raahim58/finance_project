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
        ["2026-08-12", 101, "market_source_1"]
    ]


def test_tool_evidence_json_normalization_is_exact_and_strict():
    import json
    from datetime import datetime, timezone
    from decimal import Decimal
    from app.tools.registry import tool_result

    result = tool_result("ok", [{"amount": Decimal("1.2300")}],
                         sources=[{"published_at": datetime(2026, 9, 14, tzinfo=timezone.utc)}])
    assert result["data"]["rows"] == [["1.2300"]]
    assert result["sources"][0]["published_at"] == "2026-09-14T00:00:00+00:00"
    json.dumps(result, allow_nan=False)
    with pytest.raises(TypeError, match="Unsupported evidence type"):
        tool_result("ok", {"unsupported": object()})


def test_market_overview_keeps_rankings_when_snapshot_is_missing(monkeypatch):
    from types import SimpleNamespace
    import app.tools.market_tools as market
    from app.tools.registry import expand_model_data
    day = date(2026, 9, 14)
    monkeypatch.setattr(market, "resolve_market_date", lambda *_args: day)
    monkeypatch.setattr(market, "get_market_snapshot", lambda *_args: None)
    row = SimpleNamespace(model_dump=lambda: {"symbol": "MEBL", "close": 123, "source": "stored", "trade_date": day})
    monkeypatch.setattr(market, "get_top_gainers", lambda *_args: [row])
    result = expand_model_data(market._overview(None, None, market.MarketOverviewInput(sections=["snapshot", "gainers"])))
    assert result["status"] == "ok"
    assert result["data"]["snapshot"]["status"] == "missing"
    assert result["data"]["gainers"]["records"] == [{"symbol": "MEBL", "close": 123, "source": "stored", "trade_date": "2026-09-14"}]
