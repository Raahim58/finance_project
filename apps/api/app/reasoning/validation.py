from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.reasoning.grounding import validate_references
from app.reasoning.contracts import ModelAnswer, ReasoningRequest, RecommendationLabel


def parse_model_answer(raw: str) -> tuple[ModelAnswer | None, list[str]]:
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.I)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, [f"response must be one JSON object: {exc.msg}"]
    if isinstance(parsed, dict) and "answer" not in parsed and isinstance(parsed.get("analysis"), str):
        parsed["answer"] = parsed.pop("analysis")
    try:
        return ModelAnswer.model_validate(parsed), []
    except ValidationError as exc:
        return None, [error["msg"] for error in exc.errors()]


def validate_model_answer(
    answer: ModelAnswer, request: ReasoningRequest
) -> list[str]:
    """Validate only mechanically provable Phase 8 invariants."""

    errors: list[str] = []
    if answer.portfolio_id != request.portfolio_id:
        errors.append("portfolio_id must equal the server-resolved portfolio_id")

    unknown_instruments = set(answer.instrument_ids) - request.allowed_instrument_ids
    if unknown_instruments:
        errors.append(
            "instrument_ids contain values outside the server-supplied scope: "
            + ", ".join(sorted(unknown_instruments))
        )

    unknown_evidence = set(answer.evidence_ids) - request.allowed_evidence_ids
    if unknown_evidence:
        errors.append(
            "evidence_ids contain values outside the evidence allowlist: "
            + ", ".join(sorted(unknown_evidence))
        )
    inline = set(re.findall(r"\[([^\[\]\n]+)\]", answer.answer))
    for citation in inline:
        if citation not in request.allowed_evidence_ids:
            errors.append("inline citation is not supplied evidence")
    if request.required_evidence_ids and not (
        set(answer.evidence_ids) & request.required_evidence_ids
    ):
        errors.append("at least one intent-required evidence_id must be used")

    advisory = answer.recommendation in {
        RecommendationLabel.BUY_ADD,
        RecommendationLabel.HOLD,
        RecommendationLabel.REDUCE,
        RecommendationLabel.AVOID,
    }
    if advisory and request.portfolio_id is None:
        errors.append("an advisory recommendation requires a resolved portfolio")
    if advisory and answer.horizon is None:
        errors.append("a recommendation requires a horizon")
    if advisory and answer.confidence is None:
        errors.append("a recommendation requires a confidence label")
    if answer.horizon is not None and answer.horizon.source == "ips":
        if request.portfolio_id is None:
            errors.append("an IPS horizon requires a resolved portfolio")
    if request.freshness_warnings and not answer.freshness_acknowledgements:
        errors.append("freshness warnings used by the answer must be acknowledged")
    errors.extend(validate_references(answer.answer, answer.numerical_references, request.numerical_registry))
    return errors
