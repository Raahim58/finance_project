"""Single-turn prompts, strict evidence validation, and reusable owner-scoped outputs."""

from pathlib import Path
import re
from decimal import Decimal, InvalidOperation
from app.domain.research_relevance import canonical, fingerprint
from app.schemas.research_intelligence import ProfileOutput, DigestOutput
from app.models.research_intelligence import CompanyExposureProfile, CompanyEventBrief

PROFILE_VERSION = "exposure-v4"
DIGEST_VERSION = "digest-v3"
PROMPTS = Path(__file__).resolve().parents[1] / "ai" / "prompts"


def profile_quote_options(payload):
    """Provider selects a short ID; persisted quotes always come from source text."""
    quotes = {}
    for evidence in payload.get("evidence", []):
        words = list(re.finditer(r"\S+", evidence["text"]))
        positions = [0]
        focus = next(
            (
                i
                for i, word in enumerate(words)
                if re.search(
                    r"oil|crude|interest|borrow|exchange|currency|import|export",
                    word.group(),
                    re.I,
                )
            ),
            None,
        )
        if focus is not None:
            positions.append(max(0, focus - 5))
        for start in positions:
            if words:
                end = min(len(words), start + 20)
                quote = evidence["text"][words[start].start() : words[end - 1].end()]
                if not any(q["evidence_id"] == evidence["id"] and q["text"] == quote for q in quotes.values()):
                    quotes[f"q{len(quotes)}"] = {"evidence_id": evidence["id"], "text": quote}
    return quotes


def generation_request(kind, payload):
    schema = ProfileOutput if kind == "profile" else DigestOutput
    output_schema = schema.model_json_schema()
    quotes = profile_quote_options(payload) if kind == "profile" else {}
    if quotes:
        output_schema["$defs"]["SupportingQuote"]["properties"]["quote"]["enum"] = list(quotes)
    prompt = (
        PROMPTS
        / ("company_exposure_profile.md" if kind == "profile" else "company_event_digest.md")
    ).read_text()
    data = canonical({**payload, "quote_options": quotes} if kind == "profile" else payload)
    cap = 32000 if kind == "profile" else 40000
    if len(data.encode()) > cap:
        raise ValueError("research_input_budget_exceeded")
    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": "INPUT_JSON\n" + data + "\nOUTPUT_SCHEMA\n" + canonical(output_schema),
        },
    ]
    if len(canonical(messages).encode()) > cap:
        raise ValueError("research_input_budget_exceeded")
    # Short IDs avoid large provider quote enums and character-copy errors.
    # The server resolves them to unchanged source slices before persistence.
    return messages, output_schema


def evidence_map(payload):
    evidence = (
        payload.get("evidence", [])
        + payload.get("company_evidence", [])
        + payload.get("relationship_evidence", [])
    )
    for event in payload.get("events", []):
        evidence += event.get("evidence", [])
    return {e["id"]: e for e in evidence}


def validate_output(kind, content, payload):
    schema = ProfileOutput if kind == "profile" else DigestOutput
    result = schema.model_validate_json(content)
    evidence = evidence_map(payload)
    fact_rows = {f["id"]: f for f in payload.get("facts", []) + payload.get("macro", [])}
    facts = set(fact_rows)
    if kind == "profile":
        quote_options = profile_quote_options(payload)
        for relationship in result.relationships:
            if set(relationship.evidence_ids) - evidence.keys():
                raise ValueError("unknown_evidence_id")
            quoted = set()
            for quote in relationship.supporting_quotes:
                if quote.evidence_id not in relationship.evidence_ids:
                    raise ValueError("quote_evidence_mismatch")
                if quote.quote in quote_options:
                    option = quote_options[quote.quote]
                    if option["evidence_id"] != quote.evidence_id:
                        raise ValueError("quote_evidence_mismatch")
                    quote.quote = option["text"]
                if quote.quote not in evidence[quote.evidence_id]["text"]:
                    raise ValueError("quote_not_in_source")
                quoted.add(quote.evidence_id)
            if set(relationship.evidence_ids) - quoted:
                raise ValueError("uncorroborated_relationship_evidence")
    else:
        supplied = {e["event_key"]: e for e in payload["events"]}
        returned = [e.event_key for e in result.events]
        if len(set(returned)) != len(returned) or set(returned) != set(supplied):
            raise ValueError("digest_event_keys_mismatch")
        for event in result.events:
            if event.relationship_kind != supplied[event.event_key]["relationship_kind"]:
                raise ValueError("relationship_kind_mismatch")
            local_evidence = {e["id"] for e in supplied[event.event_key].get("evidence", [])} | {
                e["id"]
                for e in payload.get("company_evidence", [])
                + payload.get("relationship_evidence", [])
            }
            claims = [event.what_happened] + event.why_it_matters + event.countereffects
            words = sum(len(c.text.split()) for c in claims) + sum(
                len(u.split()) for u in event.unknowns
            )
            if words > 160:
                raise ValueError("digest_word_budget_exceeded")
            for claim in claims:
                quantities = list(
                    re.finditer(
                        r"(?:(PKR|USD|US\$|Rs\.?)\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(billion|million|trillion|percent|%|mmcfd|bpd|barrels|MW|shares)?",
                        claim.text,
                        re.I,
                    )
                )
                quantities = [q for q in quantities if q.group(1) or q.group(3)]
                if quantities and not claim.fact_ids:
                    raise ValueError("numerical_claim_requires_structured_fact")
                scale = {
                    "million": Decimal("1000000"),
                    "billion": Decimal("1000000000"),
                    "trillion": Decimal("1000000000000"),
                }
                for quantity in quantities:
                    amount = Decimal(quantity.group(2).replace(",", "")) * scale.get(
                        (quantity.group(3) or "").lower(), Decimal(1)
                    )
                    matches = False
                    for ref in claim.fact_ids:
                        fact = fact_rows.get(ref)
                        if not fact or "value" not in fact:
                            continue
                        try:
                            value = Decimal(str(fact["value"]).replace(",", ""))
                            unit = str(fact.get("unit", "")).lower()
                            value *= next(
                                (factor for key, factor in scale.items() if key in unit), Decimal(1)
                            )
                            matches |= amount == value
                        except InvalidOperation:
                            continue
                    if not matches:
                        raise ValueError("numerical_claim_value_mismatch")
                if set(claim.evidence_ids) - local_evidence or set(claim.fact_ids) - facts:
                    raise ValueError("unknown_claim_reference")
                if event.status == "explained" and not (claim.evidence_ids or claim.fact_ids):
                    raise ValueError("uncited_claim")
    return result.model_dump(mode="json")


def brief_fingerprint(payload, event_key):
    """Other events in a batch are not dependencies of this event's saved explanation."""
    event = next(e for e in payload["events"] if e["event_key"] == event_key)
    return fingerprint({**payload, "events": [event]})


def cached_event_keys(db, user, instrument, payload, provider=None, model=None):
    from sqlalchemy import select

    hashes = {e["event_key"]: brief_fingerprint(payload, e["event_key"]) for e in payload["events"]}
    statement = select(CompanyEventBrief).where(
        CompanyEventBrief.user_id == user.id,
        CompanyEventBrief.instrument_id == instrument.id,
        CompanyEventBrief.prompt_version == DIGEST_VERSION,
        CompanyEventBrief.input_hash.in_(hashes.values()),
    )
    if provider:
        statement = statement.where(CompanyEventBrief.provider == provider)
    if model:
        statement = statement.where(CompanyEventBrief.model == model)
    rows = list(db.scalars(statement.order_by(CompanyEventBrief.generated_at.desc())))
    result = {}
    for row in rows:
        if hashes.get(row.event_key) == row.input_hash:
            result.setdefault(row.event_key, row)
    return result


def save_output(db, user, instrument, kind, payload, output, provider, model):
    key = fingerprint(payload)
    evidence = list(evidence_map(payload).values())
    if kind == "profile":
        db.add(
            CompanyExposureProfile(
                user_id=user.id,
                instrument_id=instrument.id,
                input_hash=key,
                prompt_version=PROFILE_VERSION,
                provider=provider,
                model=model,
                relationships_json=canonical(output["relationships"]),
                evidence_json=canonical(evidence),
                coverage_json=canonical(output["coverage_gaps"]),
            )
        )
    else:
        events = {e["event_key"]: e for e in payload["events"]}
        for entry in output["events"]:
            event = events[entry["event_key"]]
            references = {
                ref
                for claim in [entry["what_happened"]]
                + entry["why_it_matters"]
                + entry["countereffects"]
                for ref in claim.get("evidence_ids", [])
            }
            references.update(e["id"] for e in event.get("evidence", []))
            event_evidence = [e for e in evidence if e["id"] in references]
            db.add(
                CompanyEventBrief(
                    user_id=user.id,
                    instrument_id=instrument.id,
                    event_key=entry["event_key"],
                    normalized_event_id=event["normalized_event_id"],
                    raw_event_id=event["raw_event_id"],
                    input_hash=brief_fingerprint(payload, entry["event_key"]),
                    prompt_version=DIGEST_VERSION,
                    provider=provider,
                    model=model,
                    brief_json=canonical(entry),
                    evidence_json=canonical(event_evidence),
                )
            )
    db.flush()
