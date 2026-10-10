"""Offline read tool contracts contracts and fixtures."""

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
