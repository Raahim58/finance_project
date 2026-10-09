"""Offline evidence projection contracts and fixtures."""

from app.ai.providers.base import ContentBlock, ProviderTurn
from app.reasoning.projection import project, encode


def test_duplicate_evidence_projection_preserves_originals_and_arguments():
    from app.ai.tool_loop import _deduplicate_tool_evidence

    evidence = {"source_id": "source1", "record": "x" * 400}
    turns = [
        ProviderTurn(
            "user",
            [
                ContentBlock("tool_result", id="first", result=evidence),
                ContentBlock("tool_result", id="second", result=evidence),
            ],
        )
    ]
    projected = _deduplicate_tool_evidence(turns)
    assert projected[0].content[0].result == evidence
    assert projected[0].content[1].result["duplicate_of_tool_call_id"] == "first"
    assert turns[0].content[1].result == evidence


def test_mebl_233_subjects_224_references_have_one_prompt_copy():
    subjects = [
        {"id": f"subject-{i}", "issuer": "MEBL", "description": "Observed issuer linkage " * 4}
        for i in range(233)
    ]
    references = [
        {"evidence_id": f"event-source-{i}", "snippet": f"Unique observed passage {i} " * 4}
        for i in range(224)
    ]
    context = {"symbol": "MEBL", "subjects": subjects, "evidence": references}
    projected = project(
        {"canonical": context, "deep": [context], "deterministic_fallback": "do not send"}
    )
    raw = encode(projected)
    assert raw.count('"id":"subject-232"') == 1
    assert raw.count('"evidence_id":"event-source-223"') == 1
    assert "do not send" not in raw
    assert projected["counts"]["duplicate_records_removed"] >= 1
