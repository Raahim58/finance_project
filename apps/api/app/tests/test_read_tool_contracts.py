"""Offline read tool contracts contracts and fixtures."""

import json
import pytest
from app.tools import build_tool_registry


def test_catalog_is_generated_from_pydantic_and_refresh_is_not_allowlisted():
    registry = build_tool_registry()
    catalog = {item["name"]: item for item in registry.model_catalog()}
    assert "research.refresh_company" not in catalog
    assert {
        "research.company_sections",
        "market.universe",
        "allocation.verify",
        "documents.discover",
        "documents.read",
        "documents.navigate",
        "documents.page_images",
    } <= set(catalog)
    assert catalog["documents.discover"]["input_schema"] == next(
        item.input_model.model_json_schema()
        for item in registry.definitions()
        if item.name == "documents.discover"
    )
    with pytest.raises(KeyError, match="not allowlisted"):
        registry.invoke("research.refresh_company", None, None, {})


def test_errors_are_stable_and_do_not_expose_exception_text():
    result = build_tool_registry().invoke("documents.read", None, None, {"document_id": "x"})
    assert result["status"] == "invalid_arguments"
    assert result["data"] == {
        "error": {
            "code": "invalid_arguments",
            "fields": ["mode"],
            "details": [{"field": "mode", "type": "missing", "message": "Field required"}],
        }
    }


def test_mebl_oversized_fixture_is_a_production_shaped_reconstruction():
    subjects = [
        {
            "subject_id": f"subject-{index}",
            "entity": {"symbol": "MEBL", "type": "instrument", "resolution": "observed"},
            "event": {
                "event_id": f"event-{index // 3}",
                "classification": "results",
                "occurred_at": "2026-06-30T00:00:00Z",
                "materiality": "medium",
                "details": {"period": "Q2 2026", "source_status": "observed"},
            },
        }
        for index in range(233)
    ]
    references = [
        {
            "evidence_id": f"event-source-{index}",
            "source": {
                "title": f"MEBL official event source {index}",
                "url": f"https://example.test/mebl/{index}",
                "published_at": "2026-06-30T00:00:00Z",
            },
            "location": {"document_id": f"doc-{index // 4}", "page_number": index % 12 + 1},
            "snippet": "Observed issuer disclosure with material qualifications and period context.",
        }
        for index in range(224)
    ]
    fixture = {
        "fixture_kind": "reconstruction",
        "reconstruction_reason": "Exact historical serialized provider input was not retained.",
        "company": {"symbol": "MEBL", "name": "Meezan Bank Limited"},
        "event_subjects": subjects,
        "source_references": references,
    }
    component_bytes = {
        key: len(json.dumps(value, separators=(",", ":")).encode())
        for key, value in fixture.items()
    }
    assert len(subjects) == 233 and len(references) == 224
    assert component_bytes == {
        "fixture_kind": 16,
        "reconstruction_reason": 62,
        "company": 46,
        "event_subjects": 64402,
        "source_references": 67557,
    }
