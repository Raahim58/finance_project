import json
import re
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers.registry import get_provider
from app.ai.evidence import gate_citations
from app.ai.intent import NARRATIVE_TRIGGER_RE, detect_intent
from app.core.config import settings
from app.models.llm_key import LLMApiKey
from app.models.portfolio import Portfolio
from app.models.user import User
from app.models.workstation import AssistantMessage, Conversation, Instrument
from app.reasoning import ReasoningEngine
from app.reasoning.contracts import ReasoningRequest
from app.reasoning.peer_groups import build_peer_group_packets, peer_packet_evidence
from app.reasoning.validation import numeric_tokens_from_values
from app.schemas.assistant import AssistantMessageCreate
from app.services.llm_key_service import get_decrypted_key_for_call
from app.services.context_consumer_service import (
    build_assistant_context,
    context_citations,
    context_evidence,
    context_uncertainty,
    persist_built_assistant_context,
)
from app.services.portfolio_service import get_portfolio_or_404
from app.services.workstation_service import ips_compliance
from app.tools import build_tool_registry


ADVICE_RE = re.compile(r"\b(should|recommend|buy|sell|increase|reduce|rebalance)\b", re.I)
MARKET_DISCOVERY_RE = re.compile(
    r"market[- ]wide|which stocks?|what stocks?|stocks? to (?:buy|invest)|"
    r"where (?:should|can) i invest|what should i buy",
    re.I,
)


def _resolved_portfolio(
    db: Session,
    user: User,
    conversation: Conversation,
    requested_portfolio_id: str | None,
) -> Portfolio | None:
    """Resolve only trusted application state; never infer portfolio identity from prose."""

    trusted_id = requested_portfolio_id or conversation.portfolio_id
    if trusted_id:
        portfolio = get_portfolio_or_404(db, user, trusted_id)
        if portfolio.archived_at is not None:
            raise HTTPException(status_code=409, detail="Archived portfolios cannot be analyzed")
        return portfolio
    return db.scalar(
        select(Portfolio).where(
            Portfolio.user_id == user.id,
            Portfolio.is_default.is_(True),
            Portfolio.archived_at.is_(None),
        )
    )


def _mentioned_instruments(db: Session, question: str) -> list[Instrument]:
    """Resolve exact catalog symbols/names; this never affects portfolio ownership scope."""

    tokens = {token.upper() for token in re.findall(r"\b[A-Za-z][A-Za-z0-9.-]{1,14}\b", question)}
    normalized_question = " ".join(question.casefold().split())
    catalog = list(db.scalars(select(Instrument).order_by(Instrument.symbol)))
    return [
        instrument
        for instrument in catalog
        if instrument.symbol.upper() in tokens
        or (
            len(" ".join(instrument.name.casefold().split())) >= 4
            and " ".join(instrument.name.casefold().split()) in normalized_question
        )
    ]


def _base_portfolio_evidence(
    summary: dict[str, object] | None,
) -> tuple[list[str], list[dict[str, object]]]:
    if not summary:
        return [], []
    return (
        [
            f"Stored portfolio value is {summary['total_value']} {summary['portfolio']['base_currency']}, including cash of {summary['cash_balance']}, as of {summary.get('data_freshness_date')}."
        ],
        [
            {
                "evidence_id": "calc:portfolio_value",
                "metric": "portfolio_value",
                "value": summary["total_value"],
                "unit": summary["portfolio"]["base_currency"],
                "as_of": summary.get("data_freshness_date"),
                "source": summary.get("data_source"),
            },
            {
                "evidence_id": "calc:cash_balance",
                "metric": "cash_balance",
                "value": summary["cash_balance"],
                "unit": summary["portfolio"]["base_currency"],
                "as_of": summary.get("data_freshness_date"),
            },
        ],
    )


def _answer_risk_concentration(
    quant: dict[str, object] | None, risk_budget: dict[str, object] | None
) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not risk_budget:
        return (
            [
                "Risk concentration cannot be evaluated without a risky-sleeve risk-contribution table."
            ],
            [
                "Missing input: risky-sleeve risk-contribution table (requires at least two priced holdings)."
            ],
            [],
        )
    items = [item for item in risk_budget.get("items", []) if item.get("symbol") != "CASH"]
    if not items:
        return (
            ["Risk concentration cannot be evaluated without at least one priced holding."],
            ["No risky-sleeve holdings were available for risk decomposition."],
            [],
        )
    cutoff = str(risk_budget.get("data_cutoff"))
    by_risk = sorted(items, key=lambda item: item.get("percentage_risk") or 0, reverse=True)[:3]
    by_capital = sorted(
        items, key=lambda item: item.get("total_capital_weight") or 0, reverse=True
    )[:3]
    # HHI/effective-holdings come from quant.portfolio (price-based covariance), which is
    # independent of ledger-return availability -- a missing ledger history must not block
    # the risk-contribution table above, only the HHI figure specifically.
    portfolio_metrics = (
        quant.get("portfolio", {}) if quant and isinstance(quant.get("portfolio"), dict) else {}
    )
    hhi = portfolio_metrics.get("concentration_hhi")
    effective_holdings = 1 / hhi if hhi else None
    evidence: list[dict[str, object]] = []
    for item in by_risk:
        evidence.append(
            {
                "evidence_id": f"calc:risk_contribution:{item['symbol']}",
                "metric": "percentage_risk_contribution",
                "symbol": item["symbol"],
                "value": item.get("percentage_risk"),
                "unit": "percentage_point",
                "total_capital_weight": item.get("total_capital_weight"),
                "risky_sleeve_weight": item.get("risky_sleeve_weight"),
                "as_of": cutoff,
                "portfolio_basis": "risky_sleeve",
            }
        )
    for item in by_capital:
        evidence.append(
            {
                "evidence_id": f"calc:capital_weight:{item['symbol']}",
                "metric": "total_capital_weight",
                "symbol": item["symbol"],
                "value": item.get("total_capital_weight"),
                "unit": "decimal",
                "as_of": cutoff,
                "portfolio_basis": "total_capital",
            }
        )
    if hhi is not None:
        evidence.append(
            {
                "evidence_id": "calc:concentration_hhi",
                "metric": "concentration_hhi",
                "value": hhi,
                "unit": "ratio",
                "as_of": cutoff,
                "portfolio_basis": "total_capital",
            }
        )
    if effective_holdings is not None:
        evidence.append(
            {
                "evidence_id": "calc:effective_holdings",
                "metric": "effective_holdings",
                "value": effective_holdings,
                "unit": "count",
                "as_of": cutoff,
            }
        )
    risk_names = ", ".join(
        f"{item['symbol']} ({item.get('percentage_risk', 0):.1%} of risky-sleeve variance)"
        for item in by_risk
    )
    capital_names = ", ".join(
        f"{item['symbol']} ({item.get('total_capital_weight', 0):.1%} of total capital)"
        for item in by_capital
    )
    lines = [
        f"Modeled risk is most concentrated in {risk_names}, measured as a share of risky-sleeve return variance as of {cutoff}.",
        f"By total-capital allocation the largest positions are {capital_names}. Total-capital weight and risky-sleeve risk contribution are reported on separate denominators and should not be compared directly.",
    ]
    if hhi is not None:
        lines.append(
            f"Total-capital concentration (Herfindahl-Hirschman index, including cash) is {hhi:.3f}, equivalent to {effective_holdings:.1f} effective holdings."
        )
    uncertainty = list(risk_budget.get("diagnostics") or [])
    if hhi is None:
        uncertainty.append(
            "Missing input: portfolio concentration/covariance metrics (quant.portfolio) were unavailable; HHI and effective holdings could not be computed."
        )
    return lines, uncertainty, evidence


def _answer_performance(
    quant: dict[str, object] | None,
) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not quant:
        return (
            [
                "Performance and attribution cannot be evaluated without sufficient ledger return history."
            ],
            ["Missing input: reproducible quant metrics."],
            [],
        )
    portfolio_metrics = (
        quant.get("portfolio", {}) if isinstance(quant.get("portfolio"), dict) else {}
    )
    if portfolio_metrics.get("available") is False:
        return (
            ["Performance metrics are not yet available for this portfolio."],
            [str(portfolio_metrics.get("reason"))],
            [],
        )
    cutoff = str(quant.get("data_cutoff"))
    evidence: list[dict[str, object]] = []
    for key in (
        "arithmetic_expected_return",
        "realized_cagr",
        "annual_volatility",
        "max_drawdown",
        "historical_var_95",
        "historical_es_95",
    ):
        if key in portfolio_metrics:
            evidence.append(
                {
                    "evidence_id": f"calc:{key}",
                    "metric": key,
                    "value": portfolio_metrics[key],
                    "unit": "decimal",
                    "as_of": cutoff,
                    "run_id": quant.get("run_id"),
                    "return_basis": portfolio_metrics.get("return_basis"),
                }
            )
    lines = [
        f"Ledger time-weighted performance as of {cutoff}: CAGR {portfolio_metrics.get('realized_cagr')}, annualized volatility {portfolio_metrics.get('annual_volatility')}, max drawdown {portfolio_metrics.get('max_drawdown')}."
    ]
    uncertainty: list[str] = []
    benchmark = quant.get("benchmark") if isinstance(quant.get("benchmark"), dict) else None
    if benchmark and benchmark.get("available") is False:
        uncertainty.append(
            str(benchmark.get("reason") or "Benchmark-relative attribution is unavailable.")
        )
    elif benchmark:
        evidence.append(
            {
                "evidence_id": "calc:benchmark_beta",
                "metric": "beta",
                "value": benchmark.get("beta"),
                "unit": "ratio",
                "as_of": cutoff,
                "benchmark_symbol": benchmark.get("symbol"),
            }
        )
        evidence.append(
            {
                "evidence_id": "calc:benchmark_alpha",
                "metric": "alpha",
                "value": benchmark.get("alpha"),
                "unit": "decimal",
                "as_of": cutoff,
                "benchmark_symbol": benchmark.get("symbol"),
            }
        )
        lines.append(
            f"Relative to {benchmark.get('symbol')}, modeled beta is {benchmark.get('beta')} and annualized Jensen alpha is {benchmark.get('alpha')}."
        )
    return lines, uncertainty, evidence


def _answer_compliance(
    compliance: dict[str, object] | None,
) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not compliance:
        return (
            ["Mandate compliance cannot be evaluated without a confirmed IPS."],
            ["Missing input: confirmed IPS."],
            [],
        )
    status = compliance.get("status")
    evidence = [
        {
            "evidence_id": "calc:compliance_status",
            "metric": "compliance_status",
            "value": status,
            "as_of": str(compliance.get("evaluated_at")),
        }
    ]
    if status == "PASS":
        return (
            ["The portfolio passes every evaluated hard constraint in the confirmed IPS."],
            [],
            evidence,
        )
    if status == "BREACH":
        violations = compliance.get("violations") or []
        detail = "; ".join(str(v.get("message", v.get("label"))) for v in violations)
        return (
            [
                f"The portfolio breaches {len(violations)} evaluated mandate constraint(s): {detail}."
            ],
            [],
            evidence,
        )
    not_evaluated = compliance.get("not_evaluated") or []
    detail = "; ".join(str(v.get("message", v.get("label"))) for v in not_evaluated)
    return (
        ["Mandate compliance is not fully evaluated; see uncertainty for the missing inputs."],
        [f"{len(not_evaluated)} required check(s) could not be evaluated: {detail}."],
        evidence,
    )


def _answer_market_overview(
    freshness: dict[str, object] | None,
) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not freshness:
        return (
            ["Market status cannot be evaluated right now."],
            ["Missing input: market freshness."],
            [],
        )
    evidence = [
        {
            "evidence_id": "calc:market_data_mode",
            "metric": "market_data_mode",
            "value": freshness.get("market_data_mode"),
            "as_of": str(freshness.get("latest_trade_date")),
        },
        {
            "evidence_id": "calc:trade_date_status",
            "metric": "trade_date_status",
            "value": freshness.get("trade_date_status"),
            "as_of": str(freshness.get("latest_trade_date")),
        },
        {
            "evidence_id": "calc:exchange_session_status",
            "metric": "exchange_session_status",
            "value": freshness.get("exchange_session_status"),
        },
    ]
    lines = [
        f"Market data mode is {freshness.get('market_data_mode')} from provider {freshness.get('latest_source')}, latest trade date {freshness.get('latest_trade_date')} ({freshness.get('trade_date_status')}); the exchange session is currently {freshness.get('exchange_session_status')}."
    ]
    uncertainty = [
        str(freshness[key])
        for key in (
            "stale_warning",
            "backup_warning",
            "provider_mode_warning",
            "ingestion_staleness_warning",
        )
        if freshness.get(key)
    ]
    return lines, uncertainty, evidence


def _answer_holding_evidence(
    citations: list[dict[str, object]],
) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not citations:
        return (
            [
                "No cited document evidence met the relevance and symbol-scope threshold for this question."
            ],
            [
                "No grounded document evidence was available; try a narrower company scope or confirm the filing has been ingested."
            ],
            [],
        )
    sources = "; ".join(
        f"{item.get('symbol') or 'market'} — {item.get('title')}" for item in citations[:3]
    )
    return (
        [
            f"I found {len(citations)} symbol-scoped document citation(s) relevant to this question: {sources}. Use the quoted passages below as evidence; the document title alone is not a conclusion."
        ],
        [],
        [],
    )


def _answer_decision_request(
    compliance: dict[str, object] | None, risk_budget: dict[str, object] | None
) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not compliance:
        return (
            [
                "First confirm an IPS and refresh the portfolio valuation; a recommendation without a mandate and current weights would be ungrounded."
            ],
            ["Missing input: confirmed IPS compliance."],
            [],
        )
    evidence = [
        {
            "evidence_id": "calc:compliance_status",
            "metric": "compliance_status",
            "value": compliance.get("status"),
            "as_of": str(compliance.get("evaluated_at")),
        }
    ]
    violations = compliance.get("violations") or []
    if violations:
        first = violations[0]
        evidence.append(
            {
                "evidence_id": f"calc:ips:{first.get('code')}",
                "metric": first.get("code"),
                "value": first.get("actual"),
                "limit": first.get("limit"),
                "status": "BREACH",
            }
        )
        return (
            [
                f"Recommended next decision step: resolve the confirmed {first.get('label')} breach first. Open Build and compare a sandbox that brings the breached value inside its IPS limit, then reject it if required return, volatility, beta, liquidity or another hard constraint deteriorates beyond the mandate. No trade is inferred automatically."
            ],
            [],
            evidence,
        )
    items = [item for item in (risk_budget or {}).get("items", []) if item.get("symbol") != "CASH"]
    if items:
        largest = max(items, key=lambda item: item.get("percentage_risk") or 0)
        evidence.append(
            {
                "evidence_id": f"calc:risk_contribution:{largest.get('symbol')}",
                "metric": "percentage_risk_contribution",
                "symbol": largest.get("symbol"),
                "value": largest.get("percentage_risk"),
                "portfolio_basis": "risky_sleeve",
                "as_of": str((risk_budget or {}).get("data_cutoff")),
            }
        )
        return (
            [
                f"No evaluated hard breach is present. The most useful next comparison is a Build sandbox that reduces the largest modeled risk contributor, {largest.get('symbol')}, while preserving the required-return target and every confirmed ceiling/floor. Compare the proposal; do not treat this as an automatic sell instruction."
            ],
            list((risk_budget or {}).get("diagnostics") or []),
            evidence,
        )
    return (
        [
            "No evaluated hard breach is present. Choose the Build objective that matches the confirmed goal—required-return minimum variance for goal sufficiency, minimum variance for risk reduction, or a risk-budget objective for contribution control—and compare the trade-offs before saving a sandbox."
        ],
        ["Risk-contribution detail was unavailable, so no security-specific next step is stated."],
        evidence,
    )


def _answer_scenario(
    scenario_history: dict[str, object] | None,
) -> tuple[list[str], list[str], list[dict[str, object]]]:
    runs = (scenario_history or {}).get("history") if scenario_history else None
    if not runs:
        return (
            [
                "No scenario has been run for this portfolio; run one in the Scenario workspace before asking about stressed outcomes."
            ],
            ["Missing input: recorded scenario run."],
            [],
        )
    latest = runs[0]
    evidence = [
        {
            "evidence_id": f"calc:scenario:{latest.get('id')}",
            "metric": "scenario_pnl",
            "value": latest.get("pnl"),
            "unit": "PKR",
            "as_of": str(latest.get("data_cutoff")),
            "run_id": latest.get("id"),
        }
    ]
    lines = [
        f'The most recent scenario run "{latest.get("name")}" (data cutoff {latest.get("data_cutoff")}) modeled a stressed PnL of {latest.get("pnl")} ({latest.get("pnl_percent")}) against shocks {latest.get("shocks")}.'
    ]
    stressed_status = (latest.get("compliance") or {}).get("status")
    if stressed_status:
        lines.append(f"Stressed compliance status under this scenario is {stressed_status}.")
    return lines, [], evidence


def _answer_security_fit(
    context: dict[str, object] | None, citations: list[dict[str, object]]
) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not context:
        return (
            [
                "Security fit cannot be evaluated without canonical company, portfolio, and IPS context."
            ],
            ["Missing input: Canonical Intelligence Context."],
            [],
        )
    sections = context.get("sections") if isinstance(context.get("sections"), dict) else {}
    facts = (sections.get("company_facts") or {}).get("data") or {}
    security = facts.get("instrument") or {"symbol": context.get("symbol")}
    portfolio = (sections.get("portfolio") or {}).get("data") or {}
    ips = (sections.get("ips") or {}).get("data") or {}
    market = (sections.get("market_risk") or {}).get("data") or {}
    sector = (sections.get("sector") or {}).get("data") or {}
    macro = (sections.get("macro") or {}).get("data") or {}
    events = (sections.get("events") or {}).get("data") or []
    exposure = portfolio.get("security_exposure") or {}
    symbol = str(security.get("symbol") or context.get("symbol") or "Security")
    weight = float(exposure.get("weight") or 0)
    terms = ips.get("terms") if isinstance(ips.get("terms"), dict) else {}
    position_limit = terms.get("max_instrument_weight")
    position_headroom = (
        max(0.0, float(position_limit) - weight) if position_limit is not None else None
    )
    price = market.get("price") if isinstance(market.get("price"), dict) else {}
    risk = market.get("risk_metrics") if isinstance(market.get("risk_metrics"), dict) else {}
    company_sector = (sector.get("company_sector") or {}).get("sector") or security.get("sector")
    bottom_line = (
        f"{symbol} is already held at {weight:.2%}; fit must be judged against its existing risk budget."
        if weight
        else f"{symbol} is not currently held; fit depends on the selected portfolio and confirmed IPS."
    )
    if position_headroom is not None:
        bottom_line += f" Confirmed position headroom is {position_headroom:.2%}."
    company_parts = []
    if price:
        company_parts.append(
            f"last canonical price {float(price.get('close')):.2f} on {price.get('trade_date')}"
        )
    if risk.get("annual_volatility") is not None:
        company_parts.append(f"modeled annual volatility {float(risk['annual_volatility']):.2%}")
    if facts.get("fundamentals"):
        company_parts.append(
            f"{len(facts['fundamentals'])} structured company fact(s) are available"
        )
    macro_text = f"Regime: {str(macro.get('regime') or 'not evaluated').replace('_', ' ')}."
    contrary_text = (
        f"{len(citations)} candidate-scoped document passage(s) and {len(events)} material normalized event(s) were retrieved."
        if citations or events
        else "No candidate-scoped document passage or material normalized event was available; this is an evidence gap."
    )
    lines = [
        f"Integrated outlook\n\nBottom line\n{bottom_line}",
        f"\n\nSecurity and company setup\n{'; '.join(company_parts) or 'Current structured company inputs are incomplete'}.",
        f"\n\nPortfolio and sector fit\nCurrent security weight is {weight:.2%}; company sector is {company_sector or 'unavailable'}. Marginal portfolio risk still requires the deterministic candidate workbench.",
        f"\n\nMacro and global backdrop\n{macro_text}",
        f"\n\nPersonal fit\nOnly the selected portfolio's confirmed IPS is used. IPS version {ips.get('version', 'unavailable')} supplies every investment preference and constraint; application-level user preferences are excluded.",
        f"\n\nEvidence against the case\n{contrary_text}",
        "\n\nDecision boundary\nThis context does not justify an automatic add, reduce, or remove. Compare a deterministic candidate allocation before saving a proposal for review.",
    ]
    evidence = [
        {**item, "metric": item.get("classification")}
        for section in sections.values()
        if isinstance(section, dict)
        for item in section.get("evidence", [])
        if isinstance(item, dict) and item.get("evidence_id")
    ]
    deficiencies = (
        context.get("deficiencies") if isinstance(context.get("deficiencies"), list) else []
    )
    uncertainty = [
        str(item.get("reason"))
        for item in deficiencies
        if isinstance(item, dict) and item.get("reason")
    ]
    return lines, uncertainty, evidence


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
    canonical_context_payload: dict[str, object] | None = None,
) -> tuple[str, list[str], list[dict[str, object]], set[str]]:
    base_lines, evidence = (
        ([], []) if intent == "security_fit" else _base_portfolio_evidence(summary)
    )
    intent_evidence: list[dict[str, object]] = []
    if intent == "security_fit":
        intent_lines, uncertainty, intent_evidence = _answer_security_fit(
            canonical_context_payload, citations
        )
    elif intent == "decision_request":
        intent_lines, uncertainty, intent_evidence = _answer_decision_request(
            compliance, risk_budget
        )
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
            intent_lines.append(
                "The required structured portfolio data or cited documents are missing. Refresh market data, confirm an IPS, or upload a source document before relying on an analysis."
            )
            uncertainty.append("No grounded evidence was available.")

    required_evidence_ids = {str(item["evidence_id"]) for item in intent_evidence}
    if intent == "holding_evidence" and citations:
        required_evidence_ids = {f"citation:{item.get('id')}" for item in citations}

    evidence.extend(intent_evidence)
    lines = intent_lines + base_lines
    if intent not in ("holding_evidence", "security_fit") and citations:
        lines.append(
            f"I found {len(citations)} symbol-scoped document citation(s) relevant to this question."
        )
    elif intent == "security_fit" and NARRATIVE_TRIGGER_RE.search(question):
        uncertainty.append(
            "No contrary company-document passage met the relevance threshold; this is missing evidence, not confirmation of the case."
        )
    if compliance is not None and intent != "compliance":
        if compliance.get("status") == "BREACH":
            uncertainty.append(
                "Note: this portfolio has an active mandate breach; ask a mandate-compliance question for details."
            )
        elif compliance.get("status") == "NOT_EVALUATED":
            uncertainty.append(
                "Note: mandate compliance is not fully evaluated for this portfolio."
            )
    if (
        ADVICE_RE.search(question)
        and intent != "decision_request"
        and (not summary or not compliance or compliance.get("status") == "NOT_EVALUATED")
    ):
        lines.append(
            "I cannot provide a grounded buy/sell or rebalance recommendation until current portfolio data and a confirmed IPS are available."
        )
    if not lines:
        lines.append(
            "The required structured portfolio data or cited documents are missing. Refresh market data, confirm an IPS, or upload a source document before relying on an analysis."
        )
        uncertainty.append("No grounded evidence was available.")
    return " ".join(lines), uncertainty, evidence, required_evidence_ids


def _history(db: Session, conversation_id: str, limit: int = 12) -> list[dict[str, str]]:
    rows = list(
        db.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == conversation_id)
            .order_by(AssistantMessage.created_at.desc())
            .limit(limit)
        )
    )
    return [{"role": row.role, "content": row.content} for row in reversed(rows)]


def _conversation(
    db: Session, user: User, conversation_id: str | None, payload: AssistantMessageCreate
) -> Conversation:
    if conversation_id:
        row = db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user.id
            )
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return row
    if payload.portfolio_id:
        get_portfolio_or_404(db, user, payload.portfolio_id)
    row = Conversation(
        user_id=user.id, portfolio_id=payload.portfolio_id, title=payload.question[:120]
    )
    db.add(row)
    db.flush()
    return row


def _invoke(trace, registry, name, db, user, arguments):
    if len(trace) >= settings.assistant_max_tool_iterations:
        raise HTTPException(status_code=422, detail="Assistant tool iteration budget exhausted")
    try:
        result = registry.invoke(
            name, db, user, arguments, max_cost_units=settings.assistant_max_tool_cost_units
        )
        if name == "research.search" and isinstance(result, dict):
            # Every citation, whether from the deterministic search below or a
            # later LLM-planned tool call, is re-gated here so none can bypass
            # the symbol/entity and relevance floor.
            result = {
                **result,
                "citations": gate_citations(result.get("chunks", []), arguments.get("symbols")),
            }
        trace.append(
            {
                "tool": name,
                "version": next(
                    item.version for item in registry.definitions() if item.name == name
                ),
                "arguments": arguments,
                "status": "completed",
            }
        )
        return result
    except Exception as exc:
        trace.append(
            {"tool": name, "arguments": arguments, "status": "unavailable", "reason": str(exc)}
        )
        return None


async def run_assistant(
    db: Session, user: User, payload: AssistantMessageCreate, conversation_id: str | None = None
):
    conversation = _conversation(db, user, conversation_id, payload)
    portfolio = _resolved_portfolio(db, user, conversation, payload.portfolio_id)
    if portfolio is not None:
        payload = payload.model_copy(update={"portfolio_id": portfolio.id})
        conversation.portfolio_id = portfolio.id
    prior_history = _history(db, conversation.id)
    db.add(AssistantMessage(conversation_id=conversation.id, role="user", content=payload.question))
    registry = build_tool_registry()
    trace = []
    intent = detect_intent(payload.question)
    freshness = _invoke(trace, registry, "market.freshness", db, user, {})
    summary = quant = compliance = risk_budget = scenario_history = None
    holding_symbols: list[str] = []
    security_symbol: str | None = None
    canonical_context_payload = None
    canonical_request = None
    canonical_context = None
    mentioned_instruments = _mentioned_instruments(db, payload.question)
    if payload.instrument_id is None and len(mentioned_instruments) == 1:
        payload = payload.model_copy(update={"instrument_id": mentioned_instruments[0].id})
    if payload.instrument_id:
        canonical_request, canonical_context = build_assistant_context(
            db,
            user,
            payload.instrument_id,
            intent=intent,
            portfolio_id=payload.portfolio_id,
            question=payload.question,
        )
        security_symbol = canonical_context.symbol
        canonical_context_payload = canonical_context.model_dump(mode="json")
        trace.append(
            {
                "tool": "intelligence.canonical_context",
                "version": canonical_context.contract_version,
                "arguments": {
                    "instrument_id": payload.instrument_id,
                    "portfolio_id": canonical_context.portfolio_id,
                    "scope": canonical_context.scope.value,
                    "sections": list(canonical_context.sections),
                },
                "status": canonical_context.status,
            }
        )
    if payload.portfolio_id:
        summary = _invoke(
            trace, registry, "portfolio.summary", db, user, {"portfolio_id": payload.portfolio_id}
        )
        if summary:
            holding_symbols = list(
                dict.fromkeys(
                    [*holding_symbols, *[str(row["symbol"]) for row in summary.get("holdings", [])]]
                )
            )
        compliance = ips_compliance(db, user, payload.portfolio_id)
        if intent in ("decision_request", "risk_concentration", "performance"):
            quant = _invoke(
                trace, registry, "quant.portfolio", db, user, {"portfolio_id": payload.portfolio_id}
            )
        if intent in ("decision_request", "risk_concentration"):
            risk_budget = _invoke(
                trace,
                registry,
                "quant.risk_budget",
                db,
                user,
                {"portfolio_id": payload.portfolio_id},
            )
        if intent == "scenario":
            scenario_history = _invoke(
                trace,
                registry,
                "scenario.history",
                db,
                user,
                {"portfolio_id": payload.portfolio_id},
            )
    should_search_narrative = intent in ("holding_evidence", "scenario", "security_fit") or bool(
        NARRATIVE_TRIGGER_RE.search(payload.question)
    )
    citations: list[dict[str, object]] = (
        context_citations(canonical_context) if canonical_context else []
    )
    if canonical_context and "rag_evidence" in canonical_context.sections:
        trace.append(
            {
                "tool": "research.search",
                "version": canonical_context.contract_version,
                "arguments": {
                    "query": payload.question,
                    "portfolio_id": canonical_context.portfolio_id,
                    "symbols": [canonical_context.symbol],
                    "limit": settings.assistant_max_retrieved_chunks,
                },
                "status": "completed" if citations else "insufficient_evidence",
                "source": "canonical_context",
            }
        )
    elif should_search_narrative:
        search_arguments: dict[str, object] = {
            "query": payload.question,
            "portfolio_id": payload.portfolio_id,
            "limit": settings.assistant_max_retrieved_chunks,
        }
        narrative_symbols = [security_symbol] if security_symbol else holding_symbols
        if narrative_symbols:
            search_arguments["symbols"] = narrative_symbols
        research = _invoke(trace, registry, "research.search", db, user, search_arguments)
        citations = (research or {}).get("citations", [])
    else:
        trace.append(
            {
                "tool": "research.search",
                "status": "skipped",
                "reason": "The question is structured/quantitative; narrative document search was not required for this intent.",
            }
        )
    answer, uncertainty, evidence, required_evidence_ids = _deterministic_answer(
        payload.question,
        intent,
        summary,
        quant,
        risk_budget,
        compliance,
        freshness,
        scenario_history,
        citations,
        canonical_context_payload,
    )
    if canonical_context:
        uncertainty = list(dict.fromkeys([*uncertainty, *context_uncertainty(canonical_context)]))
    warnings = []
    if freshness:
        for key in ("stale_warning", "backup_warning"):
            if freshness.get(key):
                warnings.append(freshness[key])
    selected_provider = payload.provider
    if (
        selected_provider is None
        and user.preferences
        and user.preferences.default_llm_provider != "mock"
    ):
        configured = db.scalar(
            select(LLMApiKey.id).where(
                LLMApiKey.user_id == user.id,
                LLMApiKey.provider == user.preferences.default_llm_provider,
                LLMApiKey.is_active.is_(True),
            )
        )
        if configured:
            selected_provider = user.preferences.default_llm_provider
    synthesis: dict[str, object] = {
        "mode": "deterministic_fallback",
        "provider": None,
        "model": None,
        "reason": "No active external LLM provider is configured.",
    }
    deep_contexts: list[tuple[object, object]] = []
    if selected_provider and settings.phase8_reasoning_enabled:
        try:
            api_key, key_row = get_decrypted_key_for_call(db, user, selected_provider)
            provider = get_provider(selected_provider)
            selected_model = payload.model or key_row.default_model
            mode = (
                "market_wide"
                if payload.instrument_id is None and MARKET_DISCOVERY_RE.search(payload.question)
                else "targeted"
            )
            peer_packets = (
                build_peer_group_packets(db, payload.portfolio_id)
                if mode == "market_wide"
                else {}
            )
            discovery_evidence = peer_packet_evidence(peer_packets)
            canonical_evidence = context_evidence(canonical_context) if canonical_context else []
            citation_ids = {
                str(item.get("metadata", {}).get("citation_id")): item["evidence_id"]
                for item in canonical_evidence
                if isinstance(item.get("metadata"), dict)
                and item.get("metadata", {}).get("citation_id")
            }
            citation_evidence = [
                {
                    "evidence_id": citation_ids.get(
                        str(item.get("id")), f"citation:{item.get('id')}"
                    ),
                    **item,
                }
                for item in citations
            ]
            allowed_evidence_ids = {
                str(item["evidence_id"])
                for item in [
                    *evidence,
                    *canonical_evidence,
                    *citation_evidence,
                    *discovery_evidence,
                ]
                if item.get("evidence_id")
            }
            allowed_instrument_ids = {
                str(row["instrument_id"])
                for rows in peer_packets.values()
                for row in rows
            } or {
                instrument.id
                for instrument in mentioned_instruments
            }
            if payload.instrument_id:
                allowed_instrument_ids.add(payload.instrument_id)

            async def deepen_candidates(instrument_ids: list[str]) -> dict[str, object]:
                contexts: list[dict[str, object]] = []
                deep_evidence: list[dict[str, object]] = []
                for instrument_id in instrument_ids:
                    if canonical_context is not None and instrument_id == payload.instrument_id:
                        request, context = canonical_request, canonical_context
                    else:
                        request, context = build_assistant_context(
                            db,
                            user,
                            instrument_id,
                            intent="security_fit"
                            if compliance is not None
                            else "holding_evidence",
                            portfolio_id=payload.portfolio_id,
                            question=payload.question,
                        )
                        deep_contexts.append((request, context))
                    contexts.append(context.model_dump(mode="json"))
                    deep_evidence.extend(context_evidence(context))
                return {
                    "contexts": contexts,
                    "evidence": deep_evidence,
                    "allowed_evidence_ids": [
                        str(item["evidence_id"])
                        for item in deep_evidence
                        if item.get("evidence_id")
                    ],
                    "allowed_numeric_tokens": list(
                        numeric_tokens_from_values({"contexts": contexts, "evidence": deep_evidence})
                    ),
                }

            grounded_context = {
                "question": payload.question,
                "intent": intent,
                "canonical_context": canonical_context_payload,
                "portfolio_and_ips": {
                    "portfolio": None
                    if portfolio is None
                    else {"id": portfolio.id, "name": portfolio.name},
                    "summary": summary,
                    "compliance": compliance,
                },
                "calculated_evidence": evidence,
                "canonical_evidence": canonical_evidence,
                "source_citations": citation_evidence,
                "uncertainty": uncertainty,
                "deterministic_fallback": answer,
            }
            engine = ReasoningEngine(provider, api_key, selected_model)
            result = await engine.run(
                ReasoningRequest(
                    question=payload.question,
                    mode=mode,
                    portfolio_id=payload.portfolio_id,
                    portfolio_name=None if portfolio is None else portfolio.name,
                    history=prior_history,
                    grounded_context=grounded_context,
                    allowed_evidence_ids=allowed_evidence_ids,
                    allowed_instrument_ids=allowed_instrument_ids,
                    allowed_numeric_tokens=numeric_tokens_from_values(
                        {"question": payload.question, "grounded_context": grounded_context}
                    ),
                    required_evidence_ids=required_evidence_ids,
                    freshness_warnings=warnings,
                    sector_packets=peer_packets,
                    deepen_candidates=deepen_candidates,
                )
            )
            answer = result.answer
            trace.extend({"tool": "reasoning.phase8", **item} for item in result.trace)
            if deep_contexts and canonical_context is None:
                canonical_request, canonical_context = deep_contexts[0]
                canonical_context_payload = canonical_context.model_dump(mode="json")
            for _request, deep_context in deep_contexts:
                uncertainty = list(
                    dict.fromkeys([*uncertainty, *context_uncertainty(deep_context)])
                )
                known_citation_ids = {str(item.get("id")) for item in citations}
                citations.extend(
                    item
                    for item in context_citations(deep_context)
                    if str(item.get("id")) not in known_citation_ids
                )
            if result.validation_errors:
                uncertainty.append(
                    "Recommendation synthesis failed mechanical validation: "
                    + "; ".join(result.validation_errors)
                )
            synthesis = {
                "mode": "llm_grounded"
                if result.status == "grounded"
                else "recommendation_synthesis_unavailable",
                "provider": result.provider,
                "model": result.model,
                "reason": None
                if result.status == "grounded"
                else "Phase 8 synthesis or validation failed",
                "recommendation": result.recommendation,
                "confidence": result.confidence,
                "horizon": None if result.horizon is None else result.horizon.model_dump(),
                "instrument_ids": result.instrument_ids,
                "evidence_ids": result.evidence_ids,
                "repaired": result.repaired,
                "mode_scope": mode,
            }
        except Exception as exc:
            answer = "Recommendation Synthesis Unavailable\n\n" + answer
            uncertainty.append(
                f"LLM provider was unavailable ({type(exc).__name__}); grounded facts were preserved."
            )
            synthesis = {
                "mode": "recommendation_synthesis_unavailable",
                "provider": selected_provider,
                "model": payload.model,
                "reason": f"{type(exc).__name__}",
            }
    assistant = AssistantMessage(conversation_id=conversation.id, role="assistant", content=answer)
    db.add(assistant)
    db.flush()
    consumed = None
    context_consumptions = []
    contexts_to_persist = []
    if canonical_context and canonical_request:
        contexts_to_persist.append((canonical_request, canonical_context))
    for request, context in deep_contexts:
        if all(existing.receipt.content_hash != context.receipt.content_hash for _, existing in contexts_to_persist):
            contexts_to_persist.append((request, context))
    for index, (request, context) in enumerate(contexts_to_persist):
        current = persist_built_assistant_context(
            db,
            user,
            request,
            context,
            conversation_id=conversation.id,
            message_id=assistant.id,
            output_id=assistant.id if index == 0 else str(uuid4()),
        )
        context_consumptions.append(current)
    if context_consumptions:
        consumed = context_consumptions[0]
        assistant.context_receipt_id = consumed.receipt_record.id
        synthesis["context_receipt_ids"] = [
            item.receipt_record.id for item in context_consumptions
        ]
    assistant.evidence_json = json.dumps(
        {
            "calculated_evidence": evidence,
            "source_citations": citations,
            "uncertainty": uncertainty,
            "freshness_warnings": warnings,
            "context_contract_version": canonical_context.contract_version
            if canonical_context
            else None,
            "context_receipt": canonical_context.receipt.model_dump(mode="json")
            if canonical_context
            else None,
            "context_receipt_ids": [
                item.receipt_record.id for item in context_consumptions
            ],
            "refresh_request_id": consumed.refresh_request.id
            if consumed and consumed.refresh_request
            else None,
        },
        default=str,
    )
    assistant.tool_trace_json = json.dumps(trace, default=str)
    db.add(assistant)
    db.commit()
    db.refresh(assistant)
    return {
        "conversation_id": conversation.id,
        "message_id": assistant.id,
        "answer": answer,
        "uncertainty": uncertainty,
        "calculated_evidence": evidence,
        "source_citations": citations,
        "freshness_warnings": warnings,
        "tool_trace": trace,
        "synthesis": synthesis,
        "context_contract_version": canonical_context.contract_version
        if canonical_context
        else None,
        "context_status": consumed.context.status if consumed else None,
        "context_receipt": canonical_context.receipt.model_dump(mode="json")
        if canonical_context
        else None,
        "refresh_request_id": consumed.refresh_request.id
        if consumed and consumed.refresh_request
        else None,
        "created_at": assistant.created_at,
    }
