"""Offline research generation contracts and fixtures."""

import json
import pytest
from app.domain.research_relevance import detect_factors
from app.services.research_generation_service import validate_output


@pytest.mark.parametrize(
    "text,expected",
    [
        ("OGDC announces oil discovery and commencement of production", []),
        ("Brent crude prices rise", ["oil_price"]),
        ("US Federal Reserve policy rate cut", []),
        ("SBP monetary policy leaves policy rate unchanged", ["pk_policy_rate"]),
        ("USD/PKR exchange rate changes", ["usd_pkr"]),
        ("Pakistan inflation rises", []),
    ],
)
def test_narrow_factor_matching(text, expected):
    assert detect_factors(text) == expected


def test_generation_evidence_validation_rejects_invented_quotes_and_ids():
    payload = {
        "evidence": [{"id": "chunk:a", "text": "Floating-rate debt exposes financing costs."}]
    }
    relationship = {
        "factor": "pk_policy_rate",
        "channel": "financing",
        "mechanism": "Debt financing costs may change.",
        "conditions": [],
        "evidence_ids": ["chunk:a"],
        "supporting_quotes": [{"evidence_id": "chunk:a", "quote": "Floating-rate debt"}],
        "status": "ai_proposed",
    }
    assert validate_output(
        "profile", json.dumps({"relationships": [relationship], "coverage_gaps": []}), payload
    )
    relationship["supporting_quotes"][0]["quote"] = "Invented debt fact"
    with pytest.raises(ValueError, match="quote_not_in_source"):
        validate_output(
            "profile", json.dumps({"relationships": [relationship], "coverage_gaps": []}), payload
        )
    relationship["evidence_ids"] = ["other-owner:private-document"]
    with pytest.raises(ValueError, match="unknown_evidence_id"):
        validate_output(
            "profile", json.dumps({"relationships": [relationship], "coverage_gaps": []}), payload
        )


def test_digest_cannot_cite_other_events_and_requires_exact_event_keys():
    payload = {
        "events": [
            {
                "event_key": "raw:a",
                "relationship_kind": "direct",
                "evidence": [{"id": "chunk:a", "text": "A results"}],
            },
            {
                "event_key": "raw:b",
                "relationship_kind": "direct",
                "evidence": [{"id": "chunk:b", "text": "B results"}],
            },
        ]
    }
    entry = {
        "event_key": "raw:a",
        "relationship_kind": "direct",
        "status": "explained",
        "what_happened": {
            "text": "Results announced.",
            "evidence_ids": ["chunk:b"],
            "fact_ids": [],
        },
        "why_it_matters": [],
        "countereffects": [],
        "unknowns": [],
    }
    with pytest.raises(ValueError, match="digest_event_keys_mismatch"):
        validate_output("digest", json.dumps({"events": [entry]}), payload)
    second = {**entry, "event_key": "raw:b"}
    with pytest.raises(ValueError, match="unknown_claim_reference"):
        validate_output("digest", json.dumps({"events": [entry, second]}), payload)


def test_profile_schema_quotes_are_contiguous_source_excerpts():
    from app.services.research_generation_service import generation_request

    source = "The company earns interest income from floating rate deposits and investments held for its operating cash requirements."
    messages, schema = generation_request(
        "profile", {"evidence": [{"id": "chunk:real", "text": source}]}
    )
    prompt_schema = json.loads(messages[1]["content"].split("OUTPUT_SCHEMA\n")[1])
    quotes = prompt_schema["$defs"]["SupportingQuote"]["properties"]["quote"]["enum"]
    assert schema["$defs"]["SupportingQuote"]["properties"]["quote"]["enum"] == quotes
    supplied = json.loads(
        messages[1]["content"].split("INPUT_JSON\n")[1].split("\nOUTPUT_SCHEMA\n")[0]
    )["quote_options"]
    assert quotes and all(supplied[q]["text"] in source for q in quotes)
    assert all(supplied[q]["evidence_id"] == "chunk:real" for q in quotes)
    assert len(messages) == 2


def test_profile_quote_selection_resolves_source_text_and_rejects_wrong_source():
    payload = {
        "evidence": [
            {"id": "chunk:a", "text": "Floating-rate debt exposes financing costs."},
            {"id": "chunk:b", "text": "Foreign currency deposits carry translation risk."},
        ]
    }
    relationship = {
        "factor": "pk_policy_rate",
        "channel": "financing",
        "mechanism": "Debt financing costs may change.",
        "evidence_ids": ["chunk:a"],
        "supporting_quotes": [{"evidence_id": "chunk:a", "quote": "q0"}],
        "status": "ai_proposed",
    }
    output = validate_output(
        "profile", json.dumps({"relationships": [relationship], "coverage_gaps": []}), payload
    )
    assert (
        output["relationships"][0]["supporting_quotes"][0]["quote"]
        == payload["evidence"][0]["text"]
    )
    relationship["evidence_ids"] = ["chunk:b"]
    relationship["supporting_quotes"][0]["evidence_id"] = "chunk:b"
    with pytest.raises(ValueError, match="quote_evidence_mismatch"):
        validate_output(
            "profile", json.dumps({"relationships": [relationship], "coverage_gaps": []}), payload
        )


def test_digest_prompt_separates_narrative_numbers_from_structured_facts():
    from app.services.research_generation_service import generation_request

    payload = {
        "facts": [{"id": "fact:1", "value": "6268000000", "unit": "PKR"}],
        "macro": [{"id": "macro:1", "value": "11.5", "unit": "percent"}],
        "company_evidence": [
            {
                "id": "chunk:1",
                "text": "Net profit was 6,268 million PKR in 2025.",
                "page_number": 12,
            }
        ],
        "events": [
            {
                "event_key": "raw:1",
                "title": "Policy rate held at 11.5%",
                "event_date": "2026-07-28",
                "evidence": [
                    {"id": "chunk:2", "text": "Inflation reached 11.7%.", "page_number": 1}
                ],
            }
        ],
    }
    original = json.dumps(payload)
    messages, _ = generation_request("digest", payload)
    sent = json.loads(messages[1]["content"].split("INPUT_JSON\n")[1].split("\nOUTPUT_SCHEMA\n")[0])
    assert sent["facts"] == payload["facts"] and sent["macro"] == payload["macro"]
    assert "6,268" not in sent["company_evidence"][0]["text"]
    assert "11.7" not in sent["events"][0]["evidence"][0]["text"]
    assert "11.5" not in sent["events"][0]["title"]
    assert sent["events"][0]["event_date"] == "2026-07-28"
    assert sent["company_evidence"][0]["page_number"] == 12
    assert json.dumps(payload) == original


def test_digest_rejects_financial_quantity_without_structured_fact():
    payload = {
        "events": [
            {
                "event_key": "raw:real",
                "relationship_kind": "direct",
                "evidence": [{"id": "chunk:real", "text": "Reported results."}],
            }
        ]
    }
    output = {
        "events": [
            {
                "event_key": "raw:real",
                "relationship_kind": "direct",
                "status": "explained",
                "what_happened": {
                    "text": "Revenue was PKR 9 billion.",
                    "evidence_ids": ["chunk:real"],
                },
                "why_it_matters": [],
                "countereffects": [],
                "unknowns": [],
            }
        ]
    }
    with pytest.raises(ValueError, match="numerical_claim_requires_structured_fact"):
        validate_output("digest", json.dumps(output), payload)


def test_digest_rejects_quantity_that_differs_from_cited_database_value():
    payload = {
        "facts": [{"id": "fact:real", "value": "8000000000", "unit": "PKR"}],
        "events": [
            {
                "event_key": "raw:real",
                "relationship_kind": "direct",
                "evidence": [{"id": "chunk:real", "text": "Reported results."}],
            }
        ],
    }
    output = {
        "events": [
            {
                "event_key": "raw:real",
                "relationship_kind": "direct",
                "status": "explained",
                "what_happened": {
                    "text": "Revenue was PKR 9 billion.",
                    "evidence_ids": ["chunk:real"],
                    "fact_ids": ["fact:real"],
                },
                "why_it_matters": [],
                "countereffects": [],
                "unknowns": [],
            }
        ]
    }
    with pytest.raises(ValueError, match="numerical_claim_value_mismatch"):
        validate_output("digest", json.dumps(output), payload)
    output["events"][0]["what_happened"]["text"] = "Revenue was PKR 8 billion."
    assert validate_output("digest", json.dumps(output), payload)["events"]
