"""Scoped numerical references. A number alone is never evidence for another claim."""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pydantic import BaseModel, ConfigDict


class NumericalReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_id: str
    entity: str
    metric: str
    value: str
    unit: str
    period: str | None = None
    accounting_basis: str | None = None
    text: str


def registry(value, *, entity="portfolio"):
    result = {}
    def walk(item, scope):
        if isinstance(item, dict):
            security = item.get("instrument")
            scope = str(item.get("symbol") or item.get("instrument_id") or
                        (security.get("symbol") if isinstance(security, dict) else None) or scope)
            if "metric" in item and "value" in item and item.get("unit"):
                record = {"entity": scope, "metric": str(item["metric"]),
                    "value": str(item["value"]), "unit": str(item["unit"]),
                    "period": str(item.get("period_end") or item.get("as_of") or "") or None,
                    "accounting_basis": item.get("accounting_basis"),
                    "source_id": item.get("evidence_id") or item.get("id")}
                key = "num:" + hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[:20]
                result[key] = record
            for key, child in item.items():
                if key not in {"deterministic_fallback", "history", "question"}:
                    walk(child, scope)
        elif isinstance(item, (list, tuple)):
            for child in item:
                walk(child, scope)
    walk(value, entity)
    return result


def validate_references(answer, references, records):
    errors = []
    covered = []
    for ref in references:
        source = records.get(ref.reference_id)
        if source is None:
            errors.append("unknown_numerical_reference")
            continue
        if any(getattr(ref, key) != source.get(key) for key in
               ("entity", "metric", "unit", "period", "accounting_basis")):
            errors.append("numerical_reference_scope_mismatch")
        try:
            if Decimal(ref.value.replace(",", "")) != Decimal(str(source["value"]).replace(",", "")):
                errors.append("numerical_reference_value_mismatch")
        except InvalidOperation:
            if ref.value != str(source["value"]):
                errors.append("numerical_reference_value_mismatch")
        if not ref.text or ref.text not in answer:
            errors.append("numerical_reference_text_missing")
            continue
        # A reference must render the same signed value; percentage conversion is
        # allowed only when the source explicitly identifies a fractional unit.
        matches = re.findall(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?%?", ref.text)
        for rendered in matches:
            try:
                numeric = Decimal(rendered.rstrip("%").replace(",", ""))
                expected = Decimal(ref.value.replace(",", ""))
                if rendered.endswith("%"):
                    if ref.unit in {"decimal", "fraction"}:
                        expected *= 100
                    elif ref.unit not in {"%", "percent", "percentage"}:
                        errors.append("numerical_rendered_unit_mismatch")
                if numeric != expected:
                    errors.append("numerical_rendered_value_mismatch")
            except InvalidOperation:
                errors.append("numerical_rendered_value_invalid")
        covered.append(ref.text)
    prose = re.sub(r"\[[^\[\]\n]+\]", "", answer)
    for text in sorted(covered, key=len, reverse=True):
        prose = prose.replace(text, "")
    prose = re.sub(r"(?m)^\s*\d+\.\s", "", prose)
    if re.search(r"(?<![A-Za-z])[-+]?\d", prose):
        errors.append("unreferenced_numerical_statement")
    return list(dict.fromkeys(errors))
