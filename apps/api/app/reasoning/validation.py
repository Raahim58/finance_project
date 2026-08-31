from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from app.reasoning.contracts import ModelAnswer, ReasoningRequest, RecommendationLabel


NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?%?")


def _normalized_number(token: str) -> str:
    cleaned = token.replace(",", "").lstrip("+").lstrip("-")
    percent = cleaned.endswith("%")
    cleaned = cleaned.rstrip("%")
    if "." in cleaned:
        cleaned = cleaned.rstrip("0").rstrip(".")
    return (cleaned or "0") + ("%" if percent else "")


def numeric_tokens_from_values(value: object) -> set[str]:
    """Generate mechanically equivalent renderings for supplied structured values."""

    tokens: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            tokens.update(numeric_tokens_from_values(item))
        return tokens
    if isinstance(value, (list, tuple, set)):
        for item in value:
            tokens.update(numeric_tokens_from_values(item))
        return tokens
    if isinstance(value, bool) or value is None:
        return tokens
    if isinstance(value, (int, float, Decimal)):
        raw = str(value)
        tokens.add(_normalized_number(raw))
        try:
            decimal = Decimal(raw)
            for places in range(0, 5):
                rendered = f"{decimal * 100:.{places}f}"
                normalized = _normalized_number(rendered)
                tokens.update({normalized, normalized + "%"})
        except InvalidOperation:
            pass
        return tokens
    if isinstance(value, str):
        tokens.update(_normalized_number(item) for item in NUMBER_RE.findall(value))
    return tokens


def parse_model_answer(raw: str) -> tuple[ModelAnswer | None, list[str]]:
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.I)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, [f"response must be one JSON object: {exc.msg}"]
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
    unknown_numbers = {
        token
        for token in NUMBER_RE.findall(answer.answer)
        if _normalized_number(token) not in request.allowed_numeric_tokens
        and _normalized_number(token.rstrip("%")) not in request.allowed_numeric_tokens
    }
    if unknown_numbers:
        errors.append(
            "answer contains numbers outside supplied structured evidence: "
            + ", ".join(sorted(unknown_numbers))
        )
    return errors
