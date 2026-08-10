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
        result = registry.invoke(name, db, user, arguments)
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
            {"metric": "portfolio_value", "value": summary["total_value"], "unit": summary["portfolio"]["base_currency"], "as_of": summary.get("data_freshness_date"), "source": summary.get("data_source")},
            {"metric": "cash_balance", "value": summary["cash_balance"], "unit": summary["portfolio"]["base_currency"], "as_of": summary.get("data_freshness_date")},
        ])
        lines.append(f"Stored portfolio value is {summary['total_value']} {summary['portfolio']['base_currency']}, including cash of {summary['cash_balance']}.")
    if quant:
        portfolio_metrics = quant.get("portfolio", {})
        if portfolio_metrics.get("available") is False:
            uncertainty.append(str(portfolio_metrics.get("reason")))
        else:
            for key in ("annual_return", "annual_volatility", "max_drawdown", "historical_var_95", "historical_es_95"):
                if key in portfolio_metrics: evidence.append({"metric": key, "value": portfolio_metrics[key], "unit": "decimal", "as_of": str(quant.get("data_cutoff")), "run_id": quant.get("run_id"), "assumptions": {"annualization": quant.get("annualization"), "covariance_shrinkage": quant.get("covariance_shrinkage")}})
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


async def run_assistant(db: Session, user: User, payload: AssistantMessageCreate, conversation_id: str | None = None):
    conversation = _conversation(db, user, conversation_id, payload)
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
        grounded_context = json.dumps({"question": payload.question, "calculated_evidence": evidence, "citations": citations, "uncertainty": uncertainty}, default=str)
        response = await provider.chat(api_key, [{"role": "system", "content": "Use only the supplied evidence. Do not introduce numbers. Advice-like claims require evidence; otherwise state what is missing."}, {"role": "user", "content": grounded_context}], payload.model or key_row.default_model)
        candidate = response.content
        allowed = grounded_context + payload.question
        ungrounded_numbers = [token for token in NUMBER_RE.findall(candidate) if token.rstrip("%") not in allowed]
        if not ungrounded_numbers and "No live market or document facts were retrieved" not in candidate:
            answer = candidate
        else:
            uncertainty.append("The model draft failed numeric grounding validation; deterministic output was used.")
    assistant = AssistantMessage(conversation_id=conversation.id, role="assistant", content=answer, evidence_json=json.dumps({"calculated_evidence": evidence, "source_citations": citations, "uncertainty": uncertainty, "freshness_warnings": warnings}, default=str), tool_trace_json=json.dumps(trace, default=str))
    db.add(assistant); db.commit(); db.refresh(assistant)
    return {"conversation_id": conversation.id, "message_id": assistant.id, "answer": answer, "uncertainty": uncertainty, "calculated_evidence": evidence, "source_citations": citations, "freshness_warnings": warnings, "tool_trace": trace, "created_at": assistant.created_at}
