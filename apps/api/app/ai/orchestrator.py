import json
import re
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers.registry import get_provider
from app.core.config import settings
from app.models.llm_key import LLMApiKey
from app.models.document import Document
from app.models.user import User
from app.models.workstation import AssistantMessage, Conversation, Instrument
from app.schemas.assistant import AssistantMessageCreate
from app.services.llm_key_service import get_decrypted_key_for_call
from app.services.ingestion_service import refresh_company_research
from app.services.portfolio_service import get_portfolio_or_404
from app.services.rag_service import MIN_RELEVANCE_SCORE
from app.services.workstation_service import ips_compliance
from app.tools import build_tool_registry


NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?%?")
ADVICE_RE = re.compile(r"\b(should|recommend|buy|sell|increase|reduce|rebalance)\b", re.I)

# Checked in priority order; the first match wins. Ordering keeps "risk" questions
# from being swallowed by the broader performance/return pattern.
INTENT_PATTERNS = (
    ("security_fit", re.compile(r"worth adding|interesting right now|fit my portfolio|risks? of|contradict", re.I)),
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
NARRATIVE_TRIGGER_RE = re.compile(r"\bwhy\b|what changed|\bfiling|\bmanagement\b|\bevent|contradict", re.I)


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


def _answer_security_fit(context: dict[str, object] | None, citations: list[dict[str, object]]) -> tuple[list[str], list[str], list[dict[str, object]]]:
    if not context:
        return ["Security fit cannot be evaluated without a security and selected portfolio context."], ["Missing input: Intelligence V1 security context."], []
    security = context.get("security") or {}
    outputs = context.get("model_outputs") or {}
    relevance = outputs.get("portfolio_relevance") if isinstance(outputs, dict) else None
    if not isinstance(relevance, dict):
        return [f"{security.get('symbol', 'This security')} can be described from observed company evidence, but personal fit requires a selected portfolio."], list(context.get("missing_data") or []), []
    ownership = relevance.get("ownership") or {}
    sector = relevance.get("sector_exposure") or {}
    correlation = relevance.get("correlation") or {}
    risk_contribution = relevance.get("risk_contribution") or {}
    symbol = str(security.get("symbol") or "Security")
    observed = context.get("observed_facts") if isinstance(context.get("observed_facts"), dict) else {}
    market = observed.get("market") if isinstance(observed.get("market"), dict) else {}
    derived = outputs.get("derived_fundamentals") if isinstance(outputs.get("derived_fundamentals"), dict) else {}
    market_research = outputs.get("market_research") if isinstance(outputs.get("market_research"), dict) else {}
    market_risk = market_research.get("risk") if isinstance(market_research.get("risk"), dict) else {}
    regime = outputs.get("regime") if isinstance(outputs.get("regime"), dict) else {}
    dimensions = regime.get("dimensions") if isinstance(regime.get("dimensions"), dict) else {}
    preferences = context.get("personal_context") if isinstance(context.get("personal_context"), dict) else {}
    security_weight = float(ownership.get("weight", 0) or 0)
    sector_weight = float(sector.get("current_weight", 0) or 0)
    risk_share = float(risk_contribution.get("percentage", 0) or 0) if isinstance(risk_contribution, dict) and risk_contribution.get("available") else None
    average_correlation = float(correlation.get("average_with_holdings")) if isinstance(correlation, dict) and correlation.get("available") else None
    compliance = relevance.get("compliance") if isinstance(relevance.get("compliance"), dict) else {}
    is_synthetic = bool((context.get("evidence") or {}).get("has_synthetic_data")) if isinstance(context.get("evidence"), dict) else False

    fit_signals = []
    if sector.get("headroom") is not None and float(sector["headroom"]) > 0:
        fit_signals.append(f"{float(sector['headroom']):.2%} of confirmed sector headroom")
    if average_correlation is not None and average_correlation < 0.5:
        fit_signals.append(f"moderate average holding correlation ({average_correlation:.2f})")
    counter_signals = []
    if regime.get("regime") == "risk_off":
        counter_signals.append("the structured macro/market regime is risk-off")
    if risk_share is not None and security_weight > 0 and risk_share > security_weight:
        counter_signals.append(f"risk contribution ({risk_share:.2%}) exceeds capital weight ({security_weight:.2%})")
    if compliance.get("status") == "BREACH":
        counter_signals.append("the current portfolio already has an active IPS breach")
    if is_synthetic:
        counter_signals.append("company fundamentals and documents are demo data, not observed filings")
    if not (derived.get("valuation") or {}).get("available"):
        counter_signals.append("decision-grade valuation inputs are unavailable")

    if security_weight:
        bottom_line = f"{symbol} is already a meaningful holding at {security_weight:.2%}, so the question is whether it still earns that risk budget—not whether it is merely interesting."
    else:
        bottom_line = f"{symbol} is not currently held, so fit depends on whether its diversification and return case justify using available sector and position headroom."
    if fit_signals:
        bottom_line += f" The fit case is supported by {', and '.join(fit_signals)}."
    if counter_signals:
        bottom_line += f" The case remains conditional because {'; '.join(counter_signals)}."

    setup_parts = []
    if market:
        setup_parts.append(f"last price {float(market.get('close')):.2f} on {market.get('date')} with a {float(market.get('change_percent', 0) or 0):+.2f}% daily move")
    if market_risk.get("annual_volatility") is not None:
        setup_parts.append(f"modeled annual volatility {float(market_risk['annual_volatility']):.2%}")
    growth = derived.get("growth") if isinstance(derived.get("growth"), dict) else {}
    growth_parts = []
    for key in ("revenue", "net_income", "ebit"):
        item = growth.get(key)
        if isinstance(item, dict) and item.get("value") is not None:
            growth_parts.append(f"{key.replace('_', ' ')} {float(item['value']):+.1%}")
    ratios = derived.get("ratios") if isinstance(derived.get("ratios"), dict) else {}
    ratio_parts = []
    for key in ("operating_margin", "net_margin"):
        item = ratios.get(key)
        if isinstance(item, dict) and item.get("value") is not None:
            ratio_parts.append(f"{key.replace('_', ' ')} {float(item['value']):.1%}")
    company_text = "; ".join(setup_parts) or "current market setup is unavailable"
    if growth_parts: company_text += f". Normalized fact growth: {', '.join(growth_parts)}"
    if ratio_parts: company_text += f"; derived profitability: {', '.join(ratio_parts)}"
    if is_synthetic: company_text += ". Those company figures are demo-only and cannot support an investment conclusion"

    portfolio_parts = [f"{sector.get('sector') or 'Sector'} exposure is {sector_weight:.2%}"]
    if sector.get("headroom") is not None: portfolio_parts.append(f"sector headroom is {float(sector['headroom']):.2%}")
    if relevance.get("position_headroom") is not None: portfolio_parts.append(f"position headroom is {float(relevance['position_headroom']):.2%}")
    if average_correlation is not None: portfolio_parts.append(f"average correlation is {average_correlation:.2f}")
    if risk_share is not None: portfolio_parts.append(f"current risky-sleeve variance contribution is {risk_share:.2%}")

    macro_parts = []
    for key in ("market_breadth", "rates", "currency", "inflation", "oil"):
        item = dimensions.get(key)
        if isinstance(item, dict): macro_parts.append(f"{key.replace('_', ' ')} {item.get('status', 'not evaluated')}")
    macro_text = f"Regime: {str(regime.get('regime') or 'not evaluated').replace('_', ' ')}. " + (", ".join(macro_parts) + "." if macro_parts else "No selected structured macro dimensions are available.")
    if "oil" not in dimensions: macro_text += " Broader global-market and geopolitical context is not available in the selected structured data, so it is not inferred."

    preferred = {str(item).lower() for item in preferences.get("preferred_sectors", [])}
    avoided = {str(item).lower() for item in preferences.get("avoided_sectors", [])}
    sector_name = str(sector.get("sector") or security.get("sector") or "")
    tilt = "matches a recorded preferred-sector tilt" if sector_name.lower() in preferred else "conflicts with a recorded avoided-sector preference" if sector_name.lower() in avoided else "has no recorded personal sector tilt"
    personal_text = f"Recorded profile: {preferences.get('risk_tolerance', 'unspecified')} risk tolerance, {preferences.get('investment_horizon', 'unspecified')} horizon; {sector_name or symbol} {tilt}. The confirmed IPS remains the binding constraint."

    observed_citations = [item for item in citations if not str(item.get("source_url") or "").startswith("demo://") and "synthetic" not in str(item.get("title") or "").lower()]
    if observed_citations:
        contrary_text = f"{len(observed_citations)} candidate-scoped observed document passage(s) met the relevance threshold. Their excerpts are shown below; document retrieval establishes evidence, while any causal interpretation remains an assistant interpretation."
    else:
        contrary_text = "No candidate-scoped observed document passage established a contrary case. That is an evidence gap—not evidence that the downside case is absent."

    lines = [
        f"Integrated outlook\n\nBottom line\n{bottom_line}",
        f"\n\nSecurity and company setup\n{company_text}.",
        f"\n\nPortfolio and sector fit\n{'; '.join(portfolio_parts)}. A candidate evaluation is still required to establish the actual before/after diversification and concentration effect.",
        f"\n\nMacro and global backdrop\n{macro_text}",
        f"\n\nPersonal fit\n{personal_text}",
        f"\n\nEvidence against the case\n{contrary_text} " + ("Key structured counter-signals: " + "; ".join(counter_signals) + "." if counter_signals else "No structured counter-signal was strong enough to resolve the decision."),
        "\n\nDecision boundary\nThis context does not justify an automatic add, reduce, or remove. Evaluate a candidate allocation and compare expected return, volatility, risk contribution, stress losses, cash and IPS compliance before saving a proposal for review.",
    ]
    evidence = [
        {"evidence_id": f"calc:ownership:{symbol}", "metric": "current_weight", "symbol": symbol, "value": ownership.get("weight"), "unit": "decimal", "as_of": (relevance.get("portfolio") or {}).get("data_cutoff")},
        {"evidence_id": f"calc:sector_headroom:{symbol}", "metric": "sector_headroom", "symbol": symbol, "value": sector.get("headroom"), "limit": sector.get("limit"), "unit": "decimal"},
        {"evidence_id": f"calc:ips_status:{symbol}", "metric": "ips_compliance", "symbol": symbol, "value": compliance.get("status"), "violations": compliance.get("violations"), "as_of": compliance.get("evaluated_at")},
        {"evidence_id": f"context:personal_profile:{symbol}", "metric": "recorded_investor_preferences", "symbol": symbol, "value": preferences},
    ]
    if market:
        evidence.append({"evidence_id": f"observed:market:{symbol}", "metric": "canonical_market_observation", "symbol": symbol, "value": market, "as_of": market.get("date")})
    observed_fundamentals = observed.get("fundamentals") if isinstance(observed.get("fundamentals"), list) else []
    if observed_fundamentals:
        evidence.append({"evidence_id": f"observed:fundamentals:{symbol}", "metric": "normalized_company_facts", "symbol": symbol, "value": observed_fundamentals[:20]})
    if average_correlation is not None:
        evidence.append({"evidence_id": f"calc:average_correlation:{symbol}", "metric": "average_holding_correlation", "symbol": symbol, "value": average_correlation, "unit": "ratio", "as_of": correlation.get("data_cutoff")})
    if market_risk.get("annual_volatility") is not None:
        evidence.append({"evidence_id": f"calc:annual_volatility:{symbol}", "metric": "annual_volatility", "symbol": symbol, "value": market_risk.get("annual_volatility"), "unit": "decimal", "as_of": market_research.get("end_date")})
    evidence.append({"evidence_id": f"calc:regime:{symbol}", "metric": "macro_regime", "symbol": symbol, "value": regime.get("regime"), "as_of": next((item.get("effective_date") or item.get("trade_date") for item in dimensions.values() if isinstance(item, dict) and (item.get("effective_date") or item.get("trade_date"))), None)})
    if isinstance(risk_contribution, dict) and risk_contribution.get("available"):
        evidence.append({"evidence_id": f"calc:risk_contribution:{symbol}", "metric": "percentage_risk_contribution", "symbol": symbol, "value": risk_contribution.get("percentage"), "unit": "decimal", "as_of": risk_contribution.get("data_cutoff")})
    return lines, list(context.get("missing_data") or []), evidence


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
    security_context: dict[str, object] | None = None,
) -> tuple[str, list[str], list[dict[str, object]], set[str]]:
    base_lines, evidence = ([], []) if intent == "security_fit" else _base_portfolio_evidence(summary)
    intent_evidence: list[dict[str, object]] = []
    if intent == "security_fit":
        intent_lines, uncertainty, intent_evidence = _answer_security_fit(security_context, citations)
    elif intent == "decision_request":
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
    if intent not in ("holding_evidence", "security_fit") and citations:
        lines.append(f"I found {len(citations)} symbol-scoped document citation(s) relevant to this question.")
    elif intent == "security_fit" and NARRATIVE_TRIGGER_RE.search(question):
        uncertainty.append("No contrary company-document passage met the relevance threshold; this is missing evidence, not confirmation of the case.")
    if compliance is not None and intent != "compliance":
        if compliance.get("status") == "BREACH":
            uncertainty.append("Note: this portfolio has an active mandate breach; ask a mandate-compliance question for details.")
        elif compliance.get("status") == "NOT_EVALUATED":
            uncertainty.append("Note: mandate compliance is not fully evaluated for this portfolio.")
    if ADVICE_RE.search(question) and intent != "decision_request" and (not summary or not compliance or compliance.get("status") == "NOT_EVALUATED"):
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
        valid_cited = {str(item) for item in cited if str(item) in evidence_ids} if isinstance(cited, list) else set()
        if not valid_cited:
            return None, "At least one model claim lacked a valid evidence ID."
        cited_all.update(valid_cited)
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
    security_symbol: str | None = None
    security_context = None
    if payload.instrument_id:
        instrument = db.get(Instrument, payload.instrument_id)
        if instrument is not None:
            security_symbol = instrument.symbol
        if settings.scheduled_research_enabled and settings.market_data_mode != "mock":
            recently_refreshed = instrument is not None and db.scalar(
                select(Document.id).where(
                    Document.symbol == instrument.symbol,
                    Document.source_name != "Deterministic Demo Seed",
                    Document.created_at >= datetime.now(UTC) - timedelta(hours=6),
                ).limit(1)
            )
            if recently_refreshed:
                trace.append({"tool": "research.refresh_company", "version": "1.0", "arguments": {"instrument_id": payload.instrument_id}, "status": "skipped", "reason": "Official company evidence was refreshed within the last six hours."})
            else:
                refresh = refresh_company_research(db, payload.instrument_id, settings.research_report_limit_per_run)
                trace.append({"tool": "research.refresh_company", "version": "1.0", "arguments": {"instrument_id": payload.instrument_id}, "status": refresh.get("status"), "accepted": refresh.get("accepted"), "rejected": refresh.get("rejected")})
        security_context = _invoke(trace, registry, "intelligence.security_context", db, user, {"instrument_id": payload.instrument_id, "portfolio_id": payload.portfolio_id})
        if security_context and isinstance(security_context.get("security"), dict):
            security_symbol = str(security_context["security"]["symbol"])
    if payload.portfolio_id:
        summary = _invoke(trace, registry, "portfolio.summary", db, user, {"portfolio_id": payload.portfolio_id})
        if summary:
            holding_symbols = list(dict.fromkeys([*holding_symbols, *[str(row["symbol"]) for row in summary.get("holdings", [])]]))
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
        narrative_symbols = [security_symbol] if security_symbol else holding_symbols
        if narrative_symbols:
            search_arguments["symbols"] = narrative_symbols
        research = _invoke(trace, registry, "research.search", db, user, search_arguments)
        citations = (research or {}).get("citations", [])
    else:
        trace.append({"tool": "research.search", "status": "skipped", "reason": "The question is structured/quantitative; narrative document search was not required for this intent."})
    answer, uncertainty, evidence, required_evidence_ids = _deterministic_answer(payload.question, intent, summary, quant, risk_budget, compliance, freshness, scenario_history, citations, security_context)
    warnings = []
    if freshness:
        for key in ("stale_warning", "backup_warning"):
            if freshness.get(key): warnings.append(freshness[key])
    selected_provider = payload.provider
    if selected_provider is None and user.preferences and user.preferences.default_llm_provider != "mock":
        configured = db.scalar(select(LLMApiKey.id).where(LLMApiKey.user_id == user.id, LLMApiKey.provider == user.preferences.default_llm_provider, LLMApiKey.is_active.is_(True)))
        if configured:
            selected_provider = user.preferences.default_llm_provider
    synthesis: dict[str, object] = {"mode": "deterministic_fallback", "provider": None, "model": None, "reason": "No active external LLM provider is configured."}
    if selected_provider:
        tool_results = []
        try:
            api_key, key_row = get_decrypted_key_for_call(db, user, selected_provider)
            provider = get_provider(selected_provider)
            selected_model = payload.model or key_row.default_model
            seen_calls: set[str] = set()
            planner_history = [*prior_history, {"role": "user", "content": payload.question}]
            for _round in range(0 if intent == "security_fit" else 3):
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
            allowed_evidence_ids = sorted(
                {str(item["evidence_id"]) for item in evidence}
                | {str(item["evidence_id"]) for item in citation_evidence}
                | {str(item["evidence_id"]) for item in tool_evidence}
            )
            grounded_context = json.dumps({"question": payload.question, "intent": intent, "conversation_history": prior_history, "security_context": security_context, "calculated_evidence": evidence, "source_citations": citation_evidence, "tool_evidence": tool_evidence, "uncertainty": uncertainty, "allowed_evidence_ids": allowed_evidence_ids}, default=str)
            response = await provider.chat(api_key, [
                {"role": "system", "content": "You are the synthesis layer of a portfolio intelligence application. Use only supplied evidence; never calculate portfolio facts or introduce numbers. Do not repeat numeric values in prose; interpret their decision relevance qualitatively because deterministic evidence cards remain the numerical authority. Integrate the security, company filings, market/sector setup, macro and available global proxies, selected portfolio, IPS, investor preferences, supporting evidence, contradictions, and missing data into a decision-useful outlook. Distinguish observed facts, model outputs, assumptions, and interpretation. If evidence is synthetic or unavailable, say so and do not use it to support the thesis. For security-fit questions, structure the answer with: Bottom line; Security and company evidence; Market, sector and macro backdrop; Portfolio and personal fit; Evidence against the case; Decision boundary. Keep the answer under 700 words and use no more than 10 claims. Return one complete JSON object only, with no markdown fence or text outside it: {\"answer\":\"sectioned prose with blank lines\",\"claims\":[{\"text\":\"claim\",\"evidence_ids\":[\"id\"]}]}. Copy evidence IDs exactly from allowed_evidence_ids. Every claim must include at least one applicable allowed ID; combine related sentences into a claim when needed."},
                {"role": "user", "content": grounded_context},
            ], selected_model)
            evidence_ids = set(allowed_evidence_ids)
            validated, failure = _validated_claim_answer(response.content, grounded_context + payload.question, evidence_ids, required_evidence_ids)
            if validated:
                answer = validated
                synthesis = {"mode": "llm_grounded", "provider": response.provider, "model": response.model, "reason": None}
            elif failure:
                uncertainty.append(f"{failure} Deterministic output was used.")
                synthesis = {"mode": "deterministic_fallback", "provider": selected_provider, "model": selected_model, "reason": failure}
        except Exception as exc:
            uncertainty.append(f"LLM provider was unavailable ({type(exc).__name__}); deterministic output was used.")
            synthesis = {"mode": "deterministic_fallback", "provider": selected_provider, "model": payload.model, "reason": f"{type(exc).__name__}"}
    assistant = AssistantMessage(conversation_id=conversation.id, role="assistant", content=answer, evidence_json=json.dumps({"calculated_evidence": evidence, "source_citations": citations, "uncertainty": uncertainty, "freshness_warnings": warnings}, default=str), tool_trace_json=json.dumps(trace, default=str))
    db.add(assistant); db.commit(); db.refresh(assistant)
    return {"conversation_id": conversation.id, "message_id": assistant.id, "answer": answer, "uncertainty": uncertainty, "calculated_evidence": evidence, "source_citations": citations, "freshness_warnings": warnings, "tool_trace": trace, "synthesis": synthesis, "created_at": assistant.created_at}
