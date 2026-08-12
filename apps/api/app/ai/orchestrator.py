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
from app.services.rag_service import MIN_RELEVANCE_SCORE
from app.services.workstation_service import ips_compliance
from app.tools import build_tool_registry


NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?%?")
ADVICE_RE = re.compile(r"\b(should|recommend|buy|sell|increase|reduce|rebalance)\b", re.I)

# Checked in priority order; the first match wins. Ordering keeps "risk" questions
# from being swallowed by the broader performance/return pattern.
INTENT_PATTERNS = (
    ("decision_request", re.compile(r"what (?:should|can) i do|what do you recommend|recommendation|next (?:step|action)|how (?:should|can) i improve", re.I)),
    ("risk_concentration", re.compile(r"risk.*concentrat|concentrat.*risk|where.*risk|riskiest|risk contribut|biggest risk", re.I)),
    ("compliance", re.compile(r"\bmandate\b|\bcompliance\b|\bips\b|\bbreach\b|\bconstraint\b|\bviolat", re.I)),
    ("scenario", re.compile(r"\bscenario\b|stress test|\bshock\b|what if|hypothetical", re.I)),
    ("performance", re.compile(r"perform|\breturn\b|attribut|sharpe|\balpha\b|\bcagr\b|drawdown|tracking error|\bbeta\b", re.I)),
    ("market_overview", re.compile(r"market (overview|breadth)|\bfreshness\b|\bstale\b|market.wide|how is the market|market status", re.I)),
    ("holding_evidence", re.compile(r"\bfiling|management|\bcompany\b|\bholding\b|position in|\bstock\b|\bevidence\b|\bdocument", re.I)),
)
# Narrative document search is only useful for these question shapes; a purely
# structured question (e.g. "where is my risk concentrated") should never pull
# unrelated filings just to pad the response.
NARRATIVE_TRIGGER_RE = re.compile(r"\bwhy\b|what changed|\bfiling|\bmanagement\b|\bevent", re.I)


def _detect_intent(question: str) -> str:
    for intent, pattern in INTENT_PATTERNS:
        if pattern.search(question):
            return intent
    return "generic"


def _gate_citations(chunks: list[dict[str, object]], requested_symbols: object) -> list[dict[str, object]]:
    """Every citation must satisfy the relevance floor and, when the caller scoped the
    search to specific symbols, must actually belong to one of those symbols. This runs
    on every research.search call (deterministic and LLM-planned) so a careless or
    unscoped call cannot smuggle an off-topic filing into the evidence set."""
    allowed = {str(symbol).upper() for symbol in requested_symbols} if isinstance(requested_symbols, list) else set()
    gated: list[dict[str, object]] = []
    for chunk in chunks:
        score = chunk.get("score")
        if not isinstance(score, (int, float)) or score < MIN_RELEVANCE_SCORE:
            continue
        symbol = chunk.get("symbol")
        if allowed and (symbol is None or str(symbol).upper() not in allowed):
            continue
        citation = dict(chunk.get("citation") or {})
        if not citation:
            continue
        citation["symbol"] = symbol
        citation["relevance_score"] = score
        gated.append(citation)
    return gated


def _base_portfolio_evidence(summary: dict[str, object] | None) -> tuple[list[str], list[dict[str, object]]]:
    if not summary:
        return [], []
    return (
        [f"Stored portfolio value is {summary['total_value']} {summary['portfolio']['base_currency']}, including cash of {summary['cash_balance']}, as of {summary.get('data_freshness_date')}."],
        [
            {"evidence_id": "calc:portfolio_value", "metric": "portfolio_value", "value": summary["total_value"], "unit": summary["portfolio"]["base_currency"], "as_of": summary.get("data_freshness_date"), "source": summary.get("data_source")},
            {"evidence_id": "calc:cash_balance", "metric": "cash_balance", "value": summary["cash_balance"], "unit": summary["portfolio"]["base_currency"], "as_of": summary.get("data_freshness_date")},
        ],
    )


def _answer_risk_concentration(quant: dict[str, object] | None, risk_budget: dict[str, object] | None) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not risk_budget:
        return ["Risk concentration cannot be evaluated without a risky-sleeve risk-contribution table."], ["Missing input: risky-sleeve risk-contribution table (requires at least two priced holdings)."], []
    items = [item for item in risk_budget.get("items", []) if item.get("symbol") != "CASH"]
    if not items:
        return ["Risk concentration cannot be evaluated without at least one priced holding."], ["No risky-sleeve holdings were available for risk decomposition."], []
    cutoff = str(risk_budget.get("data_cutoff"))
    by_risk = sorted(items, key=lambda item: item.get("percentage_risk") or 0, reverse=True)[:3]
    by_capital = sorted(items, key=lambda item: item.get("total_capital_weight") or 0, reverse=True)[:3]
    # HHI/effective-holdings come from quant.portfolio (price-based covariance), which is
    # independent of ledger-return availability -- a missing ledger history must not block
    # the risk-contribution table above, only the HHI figure specifically.
    portfolio_metrics = quant.get("portfolio", {}) if quant and isinstance(quant.get("portfolio"), dict) else {}
    hhi = portfolio_metrics.get("concentration_hhi")
    effective_holdings = 1 / hhi if hhi else None
    evidence: list[dict[str, object]] = []
    for item in by_risk:
        evidence.append({"evidence_id": f"calc:risk_contribution:{item['symbol']}", "metric": "percentage_risk_contribution", "symbol": item["symbol"], "value": item.get("percentage_risk"), "unit": "percentage_point", "total_capital_weight": item.get("total_capital_weight"), "risky_sleeve_weight": item.get("risky_sleeve_weight"), "as_of": cutoff, "portfolio_basis": "risky_sleeve"})
    for item in by_capital:
        evidence.append({"evidence_id": f"calc:capital_weight:{item['symbol']}", "metric": "total_capital_weight", "symbol": item["symbol"], "value": item.get("total_capital_weight"), "unit": "decimal", "as_of": cutoff, "portfolio_basis": "total_capital"})
    if hhi is not None:
        evidence.append({"evidence_id": "calc:concentration_hhi", "metric": "concentration_hhi", "value": hhi, "unit": "ratio", "as_of": cutoff, "portfolio_basis": "total_capital"})
    if effective_holdings is not None:
        evidence.append({"evidence_id": "calc:effective_holdings", "metric": "effective_holdings", "value": effective_holdings, "unit": "count", "as_of": cutoff})
    risk_names = ", ".join(f"{item['symbol']} ({item.get('percentage_risk', 0):.1%} of risky-sleeve variance)" for item in by_risk)
    capital_names = ", ".join(f"{item['symbol']} ({item.get('total_capital_weight', 0):.1%} of total capital)" for item in by_capital)
    lines = [
        f"Modeled risk is most concentrated in {risk_names}, measured as a share of risky-sleeve return variance as of {cutoff}.",
        f"By total-capital allocation the largest positions are {capital_names}. Total-capital weight and risky-sleeve risk contribution are reported on separate denominators and should not be compared directly.",
    ]
    if hhi is not None:
        lines.append(f"Total-capital concentration (Herfindahl-Hirschman index, including cash) is {hhi:.3f}, equivalent to {effective_holdings:.1f} effective holdings.")
    uncertainty = list(risk_budget.get("diagnostics") or [])
    if hhi is None:
        uncertainty.append("Missing input: portfolio concentration/covariance metrics (quant.portfolio) were unavailable; HHI and effective holdings could not be computed.")
    return lines, uncertainty, evidence


def _answer_performance(quant: dict[str, object] | None) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not quant:
        return ["Performance and attribution cannot be evaluated without sufficient ledger return history."], ["Missing input: reproducible quant metrics."], []
    portfolio_metrics = quant.get("portfolio", {}) if isinstance(quant.get("portfolio"), dict) else {}
    if portfolio_metrics.get("available") is False:
        return ["Performance metrics are not yet available for this portfolio."], [str(portfolio_metrics.get("reason"))], []
    cutoff = str(quant.get("data_cutoff"))
    evidence: list[dict[str, object]] = []
    for key in ("arithmetic_expected_return", "realized_cagr", "annual_volatility", "max_drawdown", "historical_var_95", "historical_es_95"):
        if key in portfolio_metrics:
            evidence.append({"evidence_id": f"calc:{key}", "metric": key, "value": portfolio_metrics[key], "unit": "decimal", "as_of": cutoff, "run_id": quant.get("run_id"), "return_basis": portfolio_metrics.get("return_basis")})
    lines = [f"Ledger time-weighted performance as of {cutoff}: CAGR {portfolio_metrics.get('realized_cagr')}, annualized volatility {portfolio_metrics.get('annual_volatility')}, max drawdown {portfolio_metrics.get('max_drawdown')}."]
    uncertainty: list[str] = []
    benchmark = quant.get("benchmark") if isinstance(quant.get("benchmark"), dict) else None
    if benchmark and benchmark.get("available") is False:
        uncertainty.append(str(benchmark.get("reason") or "Benchmark-relative attribution is unavailable."))
    elif benchmark:
        evidence.append({"evidence_id": "calc:benchmark_beta", "metric": "beta", "value": benchmark.get("beta"), "unit": "ratio", "as_of": cutoff, "benchmark_symbol": benchmark.get("symbol")})
        evidence.append({"evidence_id": "calc:benchmark_alpha", "metric": "alpha", "value": benchmark.get("alpha"), "unit": "decimal", "as_of": cutoff, "benchmark_symbol": benchmark.get("symbol")})
        lines.append(f"Relative to {benchmark.get('symbol')}, modeled beta is {benchmark.get('beta')} and annualized Jensen alpha is {benchmark.get('alpha')}.")
    return lines, uncertainty, evidence


def _answer_compliance(compliance: dict[str, object] | None) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not compliance:
        return ["Mandate compliance cannot be evaluated without a confirmed IPS."], ["Missing input: confirmed IPS."], []
    status = compliance.get("status")
    evidence = [{"evidence_id": "calc:compliance_status", "metric": "compliance_status", "value": status, "as_of": str(compliance.get("evaluated_at"))}]
    if status == "PASS":
        return ["The portfolio passes every evaluated hard constraint in the confirmed IPS."], [], evidence
    if status == "BREACH":
        violations = compliance.get("violations") or []
        detail = "; ".join(str(v.get("message", v.get("label"))) for v in violations)
        return [f"The portfolio breaches {len(violations)} evaluated mandate constraint(s): {detail}."], [], evidence
    not_evaluated = compliance.get("not_evaluated") or []
    detail = "; ".join(str(v.get("message", v.get("label"))) for v in not_evaluated)
    return ["Mandate compliance is not fully evaluated; see uncertainty for the missing inputs."], [f"{len(not_evaluated)} required check(s) could not be evaluated: {detail}."], evidence


def _answer_market_overview(freshness: dict[str, object] | None) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not freshness:
        return ["Market status cannot be evaluated right now."], ["Missing input: market freshness."], []
    evidence = [
        {"evidence_id": "calc:market_data_mode", "metric": "market_data_mode", "value": freshness.get("market_data_mode"), "as_of": str(freshness.get("latest_trade_date"))},
        {"evidence_id": "calc:trade_date_status", "metric": "trade_date_status", "value": freshness.get("trade_date_status"), "as_of": str(freshness.get("latest_trade_date"))},
        {"evidence_id": "calc:exchange_session_status", "metric": "exchange_session_status", "value": freshness.get("exchange_session_status")},
    ]
    lines = [f"Market data mode is {freshness.get('market_data_mode')} from provider {freshness.get('latest_source')}, latest trade date {freshness.get('latest_trade_date')} ({freshness.get('trade_date_status')}); the exchange session is currently {freshness.get('exchange_session_status')}."]
    uncertainty = [str(freshness[key]) for key in ("stale_warning", "backup_warning", "provider_mode_warning", "ingestion_staleness_warning") if freshness.get(key)]
    return lines, uncertainty, evidence


def _answer_holding_evidence(citations: list[dict[str, object]]) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not citations:
        return ["No cited document evidence met the relevance and symbol-scope threshold for this question."], ["No grounded document evidence was available; try a narrower company scope or confirm the filing has been ingested."], []
    sources = "; ".join(f"{item.get('symbol') or 'market'} — {item.get('title')}" for item in citations[:3])
    return [f"I found {len(citations)} symbol-scoped document citation(s) relevant to this question: {sources}. Use the quoted passages below as evidence; the document title alone is not a conclusion."], [], []


def _answer_decision_request(compliance: dict[str, object] | None, risk_budget: dict[str, object] | None) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not compliance:
        return ["First confirm an IPS and refresh the portfolio valuation; a recommendation without a mandate and current weights would be ungrounded."], ["Missing input: confirmed IPS compliance."], []
    evidence = [{"evidence_id": "calc:compliance_status", "metric": "compliance_status", "value": compliance.get("status"), "as_of": str(compliance.get("evaluated_at"))}]
    violations = compliance.get("violations") or []
    if violations:
        first = violations[0]
        evidence.append({"evidence_id": f"calc:ips:{first.get('code')}", "metric": first.get("code"), "value": first.get("actual"), "limit": first.get("limit"), "status": "BREACH"})
        return [f"Recommended next decision step: resolve the confirmed {first.get('label')} breach first. Open Build and compare a sandbox that brings the breached value inside its IPS limit, then reject it if required return, volatility, beta, liquidity or another hard constraint deteriorates beyond the mandate. No trade is inferred automatically."], [], evidence
    items = [item for item in (risk_budget or {}).get("items", []) if item.get("symbol") != "CASH"]
    if items:
        largest = max(items, key=lambda item: item.get("percentage_risk") or 0)
        evidence.append({"evidence_id": f"calc:risk_contribution:{largest.get('symbol')}", "metric": "percentage_risk_contribution", "symbol": largest.get("symbol"), "value": largest.get("percentage_risk"), "portfolio_basis": "risky_sleeve", "as_of": str((risk_budget or {}).get("data_cutoff"))})
        return [f"No evaluated hard breach is present. The most useful next comparison is a Build sandbox that reduces the largest modeled risk contributor, {largest.get('symbol')}, while preserving the required-return target and every confirmed ceiling/floor. Compare the proposal; do not treat this as an automatic sell instruction."], list((risk_budget or {}).get("diagnostics") or []), evidence
    return ["No evaluated hard breach is present. Choose the Build objective that matches the confirmed goal—required-return minimum variance for goal sufficiency, minimum variance for risk reduction, or a risk-budget objective for contribution control—and compare the trade-offs before saving a sandbox."], ["Risk-contribution detail was unavailable, so no security-specific next step is stated."], evidence


def _answer_scenario(scenario_history: dict[str, object] | None) -> tuple[list[str], list[str], list[dict[str, object]]]:
    runs = (scenario_history or {}).get("history") if scenario_history else None
    if not runs:
        return ["No scenario has been run for this portfolio; run one in the Scenario workspace before asking about stressed outcomes."], ["Missing input: recorded scenario run."], []
    latest = runs[0]
    evidence = [{"evidence_id": f"calc:scenario:{latest.get('id')}", "metric": "scenario_pnl", "value": latest.get("pnl"), "unit": "PKR", "as_of": str(latest.get("data_cutoff")), "run_id": latest.get("id")}]
    lines = [f"The most recent scenario run \"{latest.get('name')}\" (data cutoff {latest.get('data_cutoff')}) modeled a stressed PnL of {latest.get('pnl')} ({latest.get('pnl_percent')}) against shocks {latest.get('shocks')}."]
    stressed_status = ((latest.get("compliance") or {}).get("status"))
    if stressed_status:
        lines.append(f"Stressed compliance status under this scenario is {stressed_status}.")
    return lines, [], evidence


def _deterministic_answer(
    question: str,
    intent: str,
    summary: dict[str, object] | None,
    quant: dict[str, object] | None,
    risk_budget: dict[str, object] | None,
    compliance: dict[str, object] | None,
    freshness: dict[str, object] | None,
    scenario_history: dict[str, object] | None,
    citations: list[dict[str, object]],
) -> tuple[str, list[str], list[dict[str, object]], set[str]]:
    base_lines, evidence = _base_portfolio_evidence(summary)
    intent_evidence: list[dict[str, object]] = []
    if intent == "decision_request":
        intent_lines, uncertainty, intent_evidence = _answer_decision_request(compliance, risk_budget)
    elif intent == "risk_concentration":
        intent_lines, uncertainty, intent_evidence = _answer_risk_concentration(quant, risk_budget)
    elif intent == "performance":
        intent_lines, uncertainty, intent_evidence = _answer_performance(quant)
    elif intent == "compliance":
        intent_lines, uncertainty, intent_evidence = _answer_compliance(compliance)
    elif intent == "market_overview":
        intent_lines, uncertainty, intent_evidence = _answer_market_overview(freshness)
    elif intent == "holding_evidence":
        intent_lines, uncertainty, intent_evidence = _answer_holding_evidence(citations)
    elif intent == "scenario":
        intent_lines, uncertainty, intent_evidence = _answer_scenario(scenario_history)
    else:
        intent_lines, uncertainty = [], []
        if not summary and not citations:
            intent_lines.append("The required structured portfolio data or cited documents are missing. Refresh market data, confirm an IPS, or upload a source document before relying on an analysis.")
            uncertainty.append("No grounded evidence was available.")

    required_evidence_ids = {str(item["evidence_id"]) for item in intent_evidence}
    if intent == "holding_evidence" and citations:
        required_evidence_ids = {f"citation:{item.get('id')}" for item in citations}

    evidence.extend(intent_evidence)
    lines = intent_lines + base_lines
    if intent != "holding_evidence" and citations:
        lines.append(f"I found {len(citations)} symbol-scoped document citation(s) relevant to this question.")
    if compliance is not None and intent != "compliance":
        if compliance.get("status") == "BREACH":
            uncertainty.append("Note: this portfolio has an active mandate breach; ask a mandate-compliance question for details.")
        elif compliance.get("status") == "NOT_EVALUATED":
            uncertainty.append("Note: mandate compliance is not fully evaluated for this portfolio.")
    if ADVICE_RE.search(question) and intent != "decision_request" and (not summary or not compliance):
        lines.append("I cannot provide a grounded buy/sell or rebalance recommendation until current portfolio data and a confirmed IPS are available.")
    if not lines:
        lines.append("The required structured portfolio data or cited documents are missing. Refresh market data, confirm an IPS, or upload a source document before relying on an analysis.")
        uncertainty.append("No grounded evidence was available.")
    return " ".join(lines), uncertainty, evidence, required_evidence_ids


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
        if name == "research.search" and isinstance(result, dict):
            # Every citation, whether from the deterministic search below or a
            # later LLM-planned tool call, is re-gated here so none can bypass
            # the symbol/entity and relevance floor.
            result = {**result, "citations": _gate_citations(result.get("chunks", []), arguments.get("symbols"))}
        trace.append({"tool": name, "version": next(item.version for item in registry.definitions() if item.name == name), "arguments": arguments, "status": "completed"})
        return result
    except Exception as exc:
        trace.append({"tool": name, "arguments": arguments, "status": "unavailable", "reason": str(exc)})
        return None


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


def _validated_claim_answer(candidate: str, context: str, evidence_ids: set[str], required_evidence_ids: set[str]) -> tuple[str | None, str | None]:
    parsed = _json_object(candidate)
    if not parsed or not isinstance(parsed.get("answer"), str) or not isinstance(parsed.get("claims"), list):
        return None, "The model draft did not use the required claim/evidence structure."
    cited_all: set[str] = set()
    for claim in parsed["claims"]:
        if not isinstance(claim, dict) or not isinstance(claim.get("text"), str):
            return None, "The model draft contained an invalid claim object."
        cited = claim.get("evidence_ids")
        if not isinstance(cited, list) or not cited or any(str(item) not in evidence_ids for item in cited):
            return None, "At least one model claim lacked a valid evidence ID."
        cited_all.update(str(item) for item in cited)
        if ADVICE_RE.search(claim["text"]) and not cited:
            return None, "An advice-like model claim lacked supporting evidence."
    if required_evidence_ids and not (cited_all & required_evidence_ids):
        return None, "The model draft did not address the structured facts required for this question's intent."
    ungrounded_numbers = [token for token in NUMBER_RE.findall(parsed["answer"]) if token.rstrip("%") not in context]
    if ungrounded_numbers:
        return None, "The model draft failed numeric grounding validation."
    return parsed["answer"], None


async def run_assistant(db: Session, user: User, payload: AssistantMessageCreate, conversation_id: str | None = None):
    conversation = _conversation(db, user, conversation_id, payload)
    prior_history = _history(db, conversation.id)
    db.add(AssistantMessage(conversation_id=conversation.id, role="user", content=payload.question))
    registry = build_tool_registry(); trace = []
    intent = _detect_intent(payload.question)
    freshness = _invoke(trace, registry, "market.freshness", db, user, {})
    summary = quant = compliance = risk_budget = scenario_history = None
    holding_symbols: list[str] = []
    if payload.portfolio_id:
        summary = _invoke(trace, registry, "portfolio.summary", db, user, {"portfolio_id": payload.portfolio_id})
        if summary:
            holding_symbols = [str(row["symbol"]) for row in summary.get("holdings", [])]
        compliance = ips_compliance(db, user, payload.portfolio_id)
        if intent in ("decision_request", "risk_concentration", "performance"):
            quant = _invoke(trace, registry, "quant.portfolio", db, user, {"portfolio_id": payload.portfolio_id})
        if intent in ("decision_request", "risk_concentration"):
            risk_budget = _invoke(trace, registry, "quant.risk_budget", db, user, {"portfolio_id": payload.portfolio_id})
        if intent == "scenario":
            scenario_history = _invoke(trace, registry, "scenario.history", db, user, {"portfolio_id": payload.portfolio_id})
    should_search_narrative = intent in ("holding_evidence", "scenario") or bool(NARRATIVE_TRIGGER_RE.search(payload.question))
    citations: list[dict[str, object]] = []
    if should_search_narrative:
        search_arguments: dict[str, object] = {"query": payload.question, "portfolio_id": payload.portfolio_id, "limit": settings.assistant_max_retrieved_chunks}
        if holding_symbols:
            search_arguments["symbols"] = holding_symbols
        research = _invoke(trace, registry, "research.search", db, user, search_arguments)
        citations = (research or {}).get("citations", [])
    else:
        trace.append({"tool": "research.search", "status": "skipped", "reason": "The question is structured/quantitative; narrative document search was not required for this intent."})
    answer, uncertainty, evidence, required_evidence_ids = _deterministic_answer(payload.question, intent, summary, quant, risk_budget, compliance, freshness, scenario_history, citations)
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
            grounded_context = json.dumps({"question": payload.question, "intent": intent, "conversation_history": prior_history, "calculated_evidence": evidence, "source_citations": citation_evidence, "tool_evidence": tool_evidence, "uncertainty": uncertainty}, default=str)
            response = await provider.chat(api_key, [
                {"role": "system", "content": "Use only supplied evidence. Return JSON with answer and claims. Each claim is {text, evidence_ids}; every claim must cite one or more supplied evidence_id values. The response must address the supplied intent using the intent-specific calculated_evidence. Do not introduce numbers or financial facts."},
                {"role": "user", "content": grounded_context},
            ], selected_model)
            evidence_ids = (
                {str(item["evidence_id"]) for item in evidence}
                | {str(item["evidence_id"]) for item in citation_evidence}
                | {str(item["evidence_id"]) for item in tool_evidence}
            )
            validated, failure = _validated_claim_answer(response.content, grounded_context + payload.question, evidence_ids, required_evidence_ids)
            if validated:
                answer = validated
            elif failure:
                uncertainty.append(f"{failure} Deterministic output was used.")
        except Exception as exc:
            uncertainty.append(f"LLM provider was unavailable ({type(exc).__name__}); deterministic output was used.")
    assistant = AssistantMessage(conversation_id=conversation.id, role="assistant", content=answer, evidence_json=json.dumps({"calculated_evidence": evidence, "source_citations": citations, "uncertainty": uncertainty, "freshness_warnings": warnings}, default=str), tool_trace_json=json.dumps(trace, default=str))
    db.add(assistant); db.commit(); db.refresh(assistant)
    return {"conversation_id": conversation.id, "message_id": assistant.id, "answer": answer, "uncertainty": uncertainty, "calculated_evidence": evidence, "source_citations": citations, "freshness_warnings": warnings, "tool_trace": trace, "created_at": assistant.created_at}
