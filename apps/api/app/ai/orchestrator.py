import json
import re
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers.registry import get_provider
from app.core.config import settings
from app.models.llm_key import LLMApiKey
from app.models.user import User
from app.models.workstation import AssistantMessage, Conversation
from app.schemas.assistant import AssistantMessageCreate
from app.services.llm_key_service import get_decrypted_key_for_call
from app.services.portfolio_service import get_portfolio_or_404
from app.services.workstation_service import ips_compliance
from app.tools import build_tool_registry


NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?%?")
ADVICE_RE = re.compile(r"\b(should|recommend|buy|sell|increase|reduce|rebalance)\b", re.I)


def _conversation(db: Session, user: User, conversation_id: str | None, payload: AssistantMessageCreate) -> Conversation:
    if conversation_id:
        row = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id))
        if row is None: raise HTTPException(status_code=404, detail="Conversation not found")
        return row
    if payload.portfolio_id: get_portfolio_or_404(db, user, payload.portfolio_id)
    row = Conversation(user_id=user.id, portfolio_id=payload.portfolio_id, title=payload.question[:120])
    db.add(row); db.flush(); return row


def _invoke(trace, registry, name, db, user, arguments):
    if len(trace) >= settings.assistant_max_tool_iterations:
        raise HTTPException(status_code=422, detail="Assistant tool iteration budget exhausted")
    try:
        result = registry.invoke(name, db, user, arguments, max_cost_units=settings.assistant_max_tool_cost_units)
        trace.append({"tool": name, "version": next(item.version for item in registry.definitions() if item.name == name), "arguments": arguments, "status": "completed"})
        return result
    except Exception as exc:
        trace.append({"tool": name, "arguments": arguments, "status": "unavailable", "reason": str(exc)})
        return None


def _deterministic_answer(question: str, summary, quant, compliance, citations) -> tuple[str, list[str], list[dict[str, object]]]:
    evidence = []
    uncertainty = []
    lines = []
    if summary:
        evidence.extend([
            {"evidence_id": "calc:portfolio_value", "metric": "portfolio_value", "value": summary["total_value"], "unit": summary["portfolio"]["base_currency"], "as_of": summary.get("data_freshness_date"), "source": summary.get("data_source")},
            {"evidence_id": "calc:cash_balance", "metric": "cash_balance", "value": summary["cash_balance"], "unit": summary["portfolio"]["base_currency"], "as_of": summary.get("data_freshness_date")},
        ])
        lines.append(f"Stored portfolio value is {summary['total_value']} {summary['portfolio']['base_currency']}, including cash of {summary['cash_balance']}.")
    if quant:
        portfolio_metrics = quant.get("portfolio", {})
        if portfolio_metrics.get("available") is False:
            uncertainty.append(str(portfolio_metrics.get("reason")))
        else:
            for key in ("arithmetic_expected_return", "realized_cagr", "annual_volatility", "max_drawdown", "historical_var_95", "historical_es_95"):
                if key in portfolio_metrics: evidence.append({"evidence_id": f"calc:{key}", "metric": key, "value": portfolio_metrics[key], "unit": "decimal", "as_of": str(quant.get("data_cutoff")), "run_id": quant.get("run_id"), "assumptions": {"annualization": quant.get("annualization"), "covariance_shrinkage": quant.get("covariance_shrinkage")}})
            lines.append("Risk metrics were calculated by the deterministic quant engine; see calculated_evidence for values and assumptions.")
    if compliance:
        if compliance.get("compliant"):
            lines.append("The portfolio currently passes the confirmed IPS checks implemented by the constraint engine.")
        else:
            uncertainty.append("IPS compliance is unavailable or has violations; no allocation recommendation is made.")
            if compliance.get("violations"): lines.append(f"IPS check found {len(compliance['violations'])} issue(s).")
    if citations:
        lines.append(f"I found {len(citations)} ownership-filtered document citation(s) relevant to the question.")
    if not lines:
        lines.append("The required structured portfolio data or cited documents are missing. Refresh market data, confirm an IPS, or upload a source document before relying on an analysis.")
        uncertainty.append("No grounded evidence was available.")
    if ADVICE_RE.search(question) and (not summary or not compliance or not compliance.get("compliant")):
        lines.append("I cannot provide a grounded buy/sell or rebalance recommendation until current portfolio data and a confirmed IPS are available.")
    return " ".join(lines), uncertainty, evidence


def _json_object(text: str) -> dict[str, object] | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.I)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _history(db: Session, conversation_id: str, limit: int = 12) -> list[dict[str, str]]:
    rows = list(db.scalars(
        select(AssistantMessage)
        .where(AssistantMessage.conversation_id == conversation_id)
        .order_by(AssistantMessage.created_at.desc())
        .limit(limit)
    ))
    return [{"role": row.role, "content": row.content} for row in reversed(rows)]


async def _planned_tool_calls(
    provider,
    api_key: str,
    model: str | None,
    registry,
    history,
    portfolio_id: str | None,
    tool_results: list[dict[str, object]],
    maximum_calls: int,
):
    definitions = [
        {
            "name": item.name,
            "description": item.description,
            "input_schema": item.input_model.model_json_schema(),
            "read_only": item.read_only,
            "requires_confirmation": item.requires_confirmation,
            "cost_class": item.cost_class,
        }
        for item in registry.definitions()
        if not item.requires_confirmation and (item.read_only or item.permission_scope == "research:refresh")
    ]
    prompt = {
        "task": (
            "Select the next safe tools needed to answer the latest user question. "
            "Use research.instruments to resolve names before requesting company data. "
            "Use research.refresh_company only when current cited documents are missing or insufficient, "
            "then search or inspect the company again. Return no calls when the evidence is sufficient. Return JSON only."
        ),
        "portfolio_id_in_scope": portfolio_id,
        "previous_tool_results": tool_results,
        "tools": definitions,
        "output_schema": {"tool_calls": [{"name": "tool.name", "arguments": {}}]},
        "maximum_calls": maximum_calls,
    }
    response = await provider.chat(
        api_key,
        [
            {"role": "system", "content": "You are a conservative tool planner. Never invent identifiers. Return a JSON object only."},
            *history,
            {"role": "user", "content": json.dumps(prompt, default=str)},
        ],
        model,
    )
    parsed = _json_object(response.content) or {}
    calls = parsed.get("tool_calls")
    return calls if isinstance(calls, list) else []


def _validated_claim_answer(candidate: str, context: str, evidence_ids: set[str]) -> tuple[str | None, str | None]:
    parsed = _json_object(candidate)
    if not parsed or not isinstance(parsed.get("answer"), str) or not isinstance(parsed.get("claims"), list):
        return None, "The model draft did not use the required claim/evidence structure."
    for claim in parsed["claims"]:
        if not isinstance(claim, dict) or not isinstance(claim.get("text"), str):
            return None, "The model draft contained an invalid claim object."
        cited = claim.get("evidence_ids")
        if not isinstance(cited, list) or not cited or any(str(item) not in evidence_ids for item in cited):
            return None, "At least one model claim lacked a valid evidence ID."
        if ADVICE_RE.search(claim["text"]) and not cited:
            return None, "An advice-like model claim lacked supporting evidence."
    ungrounded_numbers = [token for token in NUMBER_RE.findall(parsed["answer"]) if token.rstrip("%") not in context]
    if ungrounded_numbers:
        return None, "The model draft failed numeric grounding validation."
    return parsed["answer"], None


async def run_assistant(db: Session, user: User, payload: AssistantMessageCreate, conversation_id: str | None = None):
    conversation = _conversation(db, user, conversation_id, payload)
    prior_history = _history(db, conversation.id)
    db.add(AssistantMessage(conversation_id=conversation.id, role="user", content=payload.question))
    registry = build_tool_registry(); trace = []
    freshness = _invoke(trace, registry, "market.freshness", db, user, {})
    summary = quant = compliance = None
    if payload.portfolio_id:
        summary = _invoke(trace, registry, "portfolio.summary", db, user, {"portfolio_id": payload.portfolio_id})
        if re.search(r"risk|volatility|drawdown|var|sharpe|quant|beta|allocation|rebalance", payload.question, re.I):
            quant = _invoke(trace, registry, "quant.portfolio", db, user, {"portfolio_id": payload.portfolio_id})
        compliance = ips_compliance(db, user, payload.portfolio_id)
    research = _invoke(trace, registry, "research.search", db, user, {"query": payload.question, "portfolio_id": payload.portfolio_id, "limit": settings.assistant_max_retrieved_chunks})
    citations = (research or {}).get("citations", [])
    answer, uncertainty, evidence = _deterministic_answer(payload.question, summary, quant, compliance, citations)
    warnings = []
    if freshness:
        for key in ("stale_warning", "backup_warning"):
            if freshness.get(key): warnings.append(freshness[key])
    if payload.provider:
        api_key, key_row = get_decrypted_key_for_call(db, user, payload.provider)
        provider = get_provider(payload.provider)
        selected_model = payload.model or key_row.default_model
        tool_results = []
        try:
            seen_calls: set[str] = set()
            planner_history = [*prior_history, {"role": "user", "content": payload.question}]
            for _round in range(3):
                remaining = settings.assistant_max_tool_iterations - len(trace)
                if remaining <= 0:
                    break
                calls = await _planned_tool_calls(
                    provider,
                    api_key,
                    selected_model,
                    registry,
                    planner_history,
                    payload.portfolio_id,
                    tool_results,
                    remaining,
                )
                executed = False
                for call in calls[:remaining]:
                    if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not isinstance(call.get("arguments"), dict):
                        continue
                    signature = json.dumps({"name": call["name"], "arguments": call["arguments"]}, sort_keys=True, default=str)
                    if signature in seen_calls:
                        continue
                    seen_calls.add(signature)
                    result = _invoke(trace, registry, call["name"], db, user, call["arguments"])
                    if result is not None:
                        tool_results.append({"tool": call["name"], "arguments": call["arguments"], "result": result})
                    executed = True
                    if len(trace) >= settings.assistant_max_tool_iterations:
                        break
                if not executed:
                    break
            tool_evidence = [
                {"evidence_id": f"tool:{item['tool']}:{index + 1}", **item}
                for index, item in enumerate(tool_results)
            ]
            citation_evidence = [{"evidence_id": f"citation:{item.get('id')}", **item} for item in citations]
            grounded_context = json.dumps({"question": payload.question, "conversation_history": prior_history, "calculated_evidence": evidence, "source_citations": citation_evidence, "tool_evidence": tool_evidence, "uncertainty": uncertainty}, default=str)
            response = await provider.chat(api_key, [
                {"role": "system", "content": "Use only supplied evidence. Return JSON with answer and claims. Each claim is {text, evidence_ids}; every claim must cite one or more supplied evidence_id values. Do not introduce numbers or financial facts."},
                {"role": "user", "content": grounded_context},
            ], selected_model)
            evidence_ids = (
                {str(item["evidence_id"]) for item in evidence}
                | {str(item["evidence_id"]) for item in citation_evidence}
                | {str(item["evidence_id"]) for item in tool_evidence}
            )
            validated, failure = _validated_claim_answer(response.content, grounded_context + payload.question, evidence_ids)
            if validated:
                answer = validated
            elif failure:
                uncertainty.append(f"{failure} Deterministic output was used.")
        except Exception as exc:
            uncertainty.append(f"LLM provider was unavailable ({type(exc).__name__}); deterministic output was used.")
    assistant = AssistantMessage(conversation_id=conversation.id, role="assistant", content=answer, evidence_json=json.dumps({"calculated_evidence": evidence, "source_citations": citations, "uncertainty": uncertainty, "freshness_warnings": warnings}, default=str), tool_trace_json=json.dumps(trace, default=str))
    db.add(assistant); db.commit(); db.refresh(assistant)
    return {"conversation_id": conversation.id, "message_id": assistant.id, "answer": answer, "uncertainty": uncertainty, "calculated_evidence": evidence, "source_citations": citations, "freshness_warnings": warnings, "tool_trace": trace, "created_at": assistant.created_at}
