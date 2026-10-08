from types import SimpleNamespace

from app.tools.registry import expand_model_data
from app.tools.portfolio_tools import PortfolioEventExposureInput, _event_exposure


def test_event_exposure_is_compact_cited_and_states_impact_not_calculated(monkeypatch):
    long_text = "x" * 900
    row = {
        "event": {"title": "FFC dividend", "occurred_at": "2026-10-07", "event_type": "dividend", "materiality": "medium",
                  "freshness_status": "fresh", "evidence": [{"source_name": "PSX", "source_url": "https://dps.psx.com.pk/a", "document_id": "d1", "text": long_text},
                                                          {"source_name": "PSX", "source_url": "https://dps.psx.com.pk/b", "document_id": "d2", "text": "b"},
                                                          {"source_name": "PSX", "source_url": "https://dps.psx.com.pk/c", "document_id": "d3", "text": "c"}]},
        "companies": [{"symbol": "FFC", "relationship_kind": "direct", "current_portfolio_weight": "0.181"}],
        "potentially_affected_weight": "0.181",
    }
    monkeypatch.setattr("app.services.research_intelligence_service.portfolio_intelligence",
                        lambda *_args: {"events": [row], "coverage": {"holdings": 8}, "valuation_complete": True})
    result = _event_exposure(None, SimpleNamespace(id="u"), PortfolioEventExposureInput(portfolio_id="p"))
    assert result["status"] == "ok"
    event = expand_model_data(result["data"])["events"][0]
    assert event["impact"] == "not_calculated" and event["affected_holdings"][0]["symbol"] == "FFC"
    assert len(event["evidence"]) == 2 and len(event["evidence"][0]["text"]) <= 260
    assert {s["id"] for s in result["sources"]} == set(event["source_refs"])


def test_event_exposure_reports_missing_when_no_events(monkeypatch):
    monkeypatch.setattr("app.services.research_intelligence_service.portfolio_intelligence",
                        lambda *_args: {"events": [], "coverage": {}, "valuation_complete": True})
    assert _event_exposure(None, SimpleNamespace(id="u"), PortfolioEventExposureInput(portfolio_id="p"))["status"] == "missing"
