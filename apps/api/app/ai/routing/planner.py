"""Route decision -> exact first-pass tool calls, bounded by the route contract.

Deterministic and model-free. The planner is the only place that maps evidence
block types to read tools. Exact values stay with SQL-backed tools; the search
block only retrieves document text.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field

from app.ai.providers.base import ContentBlock
from app.ai.routing.contracts import CONTRACTS, SECTIONS
from app.ai.routing.rules import route_query
from app.domain.evidence_query import ALTERNATIVES
from app.ai.routing.types import (
    UNAVAILABLE_BLOCKS, Block, BudgetLog, PlanStep, RetrievalContract, Route,
    RouteDecision, RouterInput,
)

log = logging.getLogger(__name__)

FOLLOW_UP_RESERVE = 4          # calls kept for model-directed follow-ups/verification
SECONDARY_PRIORITY = 1000      # secondary-route blocks are trimmed before primary ones
PLANNER_VERSION = 'route-planner.v4'

# Optional blocks the question itself asks for are promoted to required, so budget
# pressure cannot trim them ahead of per-holding detail (seen live: the model had to
# fetch market data / performance itself because pass 1 dropped or lacked them).
RISK_WORDS = re.compile(r'\brisks?\b|\bvolatil|\bbeta\b|\bsharpe\b|\bdrawdown\b|\bdownside\b', re.I)
ALTERNATIVE_WORDS = ALTERNATIVES
MAX_HOLDINGS_QUANT = 10
UNIVERSE_SCREEN = ['score', 'sector_percentile', 'completeness', 'growth_flag', 'net_margin', 'liquidity']
EVENT_WORDS = re.compile(r'\bevents?\b|\bnews\b|\bannouncements?\b|\bheadlines?\b|\bexposure\b', re.I)
PERFORMANCE_WORDS = re.compile(r'\bgoals?\b|\bperformance\b|\breturns?\b|\bdrawdown\b|\bcagr\b|\bmeet\b', re.I)


@dataclass
class RoutedPlan:
    calls: list[ContentBlock]
    decision: RouteDecision
    steps: list[PlanStep] = field(default_factory=list)
    budget: BudgetLog | None = None
    missing_blocks: list[dict] = field(default_factory=list)

    def to_record(self) -> dict:
        """Inspectable routing record, safe to persist (no question text)."""
        return {
            'planner_version': PLANNER_VERSION,
            'decision': self.decision.to_dict(),
            'blocks': [{'block': s.block.value, 'tool': s.tool, 'required': s.required,
                        'source_route': s.source_route.value} for s in self.steps],
            'budget': asdict(self.budget) if self.budget else None,
            'missing_blocks': self.missing_blocks,
        }


ROUTE_DIGEST_SECTIONS = {
    # Only the sections the route's question needs: each digest section costs ~1.2k tokens
    # per issuer, and the unfiltered default (7 sections x 2 issuers) was ~60% of every call.
    Route.PORTFOLIO_IMPACT: ['material_developments', 'sector_macro', 'risks'],
    Route.PORTFOLIO_REVIEW: ['financial_performance', 'risks'],
    Route.PORTFOLIO_REBALANCE: ['financial_performance', 'earnings_drivers', 'risks'],
    Route.MULTI_STOCK_COMPARE: ['financial_performance', 'earnings_drivers', 'risks'],
    Route.SINGLE_STOCK_QUICK_TAKE: ['financial_performance', 'material_developments', 'risks'],
}


def digest_sections(question: str, route: Route | None = None) -> list[str]:
    from app.domain.evidence_query import dividend_query, DIVIDEND_SUPPORT
    if dividend_query(question):
        if re.search(r'\b(subsidiar\w*|associates?|dividends? received|dividend income)\b', question, re.I):
            return ['financial_performance', 'earnings_drivers', 'dividends']
        return ['dividends', 'financial_performance', 'risks'] if DIVIDEND_SUPPORT.search(question) else ['dividends']
    if route in ROUTE_DIGEST_SECTIONS:
        return list(ROUTE_DIGEST_SECTIONS[route])
    if re.search(r'\b(risk|wrong|investments)\b', question, re.I):
        return ['financial_performance', 'risks', 'sector_macro', 'material_developments']
    return ['financial_performance', 'earnings_drivers', 'dividends',
            'material_developments', 'expansion', 'sector_macro', 'risks']


def _entities(identity: dict) -> list[dict]:
    entities = list(identity.get('mentioned_instrument_candidates') or [])
    explicit = identity.get('explicit_instrument')
    if not entities and explicit:
        entities = [explicit]
    return entities


def _allowed_blocks(contract: RetrievalContract, secondary: tuple[Route, ...]) -> dict[Block, Route]:
    """Allowed block -> originating route, in assembly order, forbidden removed."""
    allowed: dict[Block, Route] = {}
    for block in contract.required + contract.optional:
        allowed.setdefault(block, contract.route)
    for route in secondary:
        other = CONTRACTS[route]
        if other.primary_only:
            continue
        for block in other.as_secondary:
            allowed.setdefault(block, route)
    return {b: r for b, r in allowed.items() if b not in contract.forbidden}


def enforce_budget(steps: list[PlanStep], cap: int) -> tuple[list[PlanStep], BudgetLog]:
    """Trim to `cap` calls. Drop order: secondary/optional tail, optional search,
    required tail, required search. Required steps beyond the cap are recorded as
    missing rather than sent oversized."""
    log_ = BudgetLog(cap=cap, pre_steps=len(steps), post_steps=len(steps))
    kept = list(steps)

    def rank(step: PlanStep):
        return (step.required, step.block is Block.EVIDENCE_SEARCH, -step.priority)

    while len(kept) > cap:
        victim = min(kept, key=rank)
        kept.remove(victim)
        reason = 'required_over_cap' if victim.required else 'optional_over_cap'
        log_.dropped.append({'block': victim.block.value, 'tool': victim.tool, 'reason': reason,
                             'source_route': victim.source_route.value})
        if victim.required:
            log_.missing_required.append(victim.block.value)
    log_.post_steps = len(kept)
    return kept, log_


def rule_decision(identity: dict, question: str, company_only: bool) -> RouteDecision:
    """Rule-router decision for server-resolved entities; used before any tie-break."""
    return route_query(RouterInput(
        question, tuple(e.get('symbol', '') for e in _entities(identity)),
        portfolio_selected=bool(identity.get('portfolio')), company_only=company_only))


def plan_initial_evidence(identity: dict, question: str, company_only: bool, allowance: int,
                          *, use_digests: bool = False, decision: RouteDecision | None = None,
                          completed_tools: tuple[str, ...] = ()) -> RoutedPlan:
    entities = _entities(identity)
    named_entities = bool(entities)
    selected = identity.get('portfolio')
    decision = decision or rule_decision(identity, question, company_only)
    contract = CONTRACTS[decision.primary]
    price_only = 'price_only' in decision.flags
    allowed = _allowed_blocks(contract, decision.secondary)
    missing: list[dict] = []

    portfolio = None
    if selected and not company_only and not price_only and contract.portfolio_context != 'never':
        portfolio = selected
    if portfolio is None:
        for block in tuple(allowed):
            if block in (Block.PORTFOLIO_SNAPSHOT, Block.IPS_COMPLIANCE, Block.PORTFOLIO_QUANT, Block.PORTFOLIO_EVENTS):
                if block in contract.required:
                    missing.append({'block': block.value, 'reason': 'no_portfolio_selected'})
                allowed.pop(block)
    elif contract.portfolio_context == 'if_selected':
        # Selected portfolio and confirmed IPS are explicit application context.
        for block in (Block.IPS_COMPLIANCE, Block.PORTFOLIO_SNAPSHOT):
            if block not in contract.forbidden:
                allowed = {block: contract.route, **allowed} if block not in allowed else allowed
    holdings_wide = bool(portfolio and not entities and contract.entity_blocks
                         and Block.SECURITY_QUANT in contract.required)
    if portfolio and not entities and contract.entity_blocks:
        entities = list(identity.get('portfolio_instruments') or [])
    if not contract.entity_blocks:
        entities = []
    # Portfolio-wide rebalancing needs risk/return for every holding in pass 1 (a follow-up
    # call per holding was the cost driver); everything else stays at max_entities.
    entities = entities[:MAX_HOLDINGS_QUANT if holdings_wide else contract.max_entities]
    for block in contract.required:
        if block in UNAVAILABLE_BLOCKS:
            missing.append({'block': block.value, 'reason': 'no_data_source'})
    if price_only:
        allowed = {b: r for b, r in allowed.items() if b is Block.PRICE_SNAPSHOT}

    steps: list[PlanStep] = []

    def add(block: Block, tool: str, arguments: dict, required_ok: bool = True, promote: bool = False):
        origin = allowed[block]
        required = required_ok and (block in contract.required and origin == contract.route
                                    or (promote and block in contract.optional))
        priority = len(steps) + (0 if origin == contract.route else SECONDARY_PRIORITY)
        steps.append(PlanStep(block, tool, arguments, required, origin, priority))

    if portfolio:
        pid = {'portfolio_id': portfolio['portfolio_id']}
        if Block.PORTFOLIO_SNAPSHOT in allowed and 'portfolio.summary' not in completed_tools:
            add(Block.PORTFOLIO_SNAPSHOT, 'portfolio.summary', dict(pid))
        if Block.IPS_COMPLIANCE in allowed:
            add(Block.IPS_COMPLIANCE, 'ips.compliance', dict(pid))
        if Block.PORTFOLIO_QUANT in allowed and not named_entities:
            add(Block.PORTFOLIO_QUANT, 'quant.portfolio', dict(pid))
        if Block.PORTFOLIO_EVENTS in allowed:
            add(Block.PORTFOLIO_EVENTS, 'portfolio.event_exposure', {**pid, 'limit': 8},
                promote=bool(EVENT_WORDS.search(question)))
        wants_performance = bool(PERFORMANCE_WORDS.search(question))
        if Block.PORTFOLIO_PERFORMANCE in allowed and (wants_performance or Block.PORTFOLIO_PERFORMANCE in contract.required):
            add(Block.PORTFOLIO_PERFORMANCE, 'portfolio.performance', {**pid, 'limit': 365},
                promote=wants_performance)

    if (Block.MARKET_UNIVERSE in allowed and portfolio and not price_only
            and ALTERNATIVE_WORDS.search(question)):
        held = [e['instrument_id'] for e in (identity.get('portfolio_instruments') or [])]
        add(Block.MARKET_UNIVERSE, 'market.universe',
            {'limit': 8, 'rank_by': 'score', 'screening_fields': UNIVERSE_SCREEN,
             'exclude_instrument_ids': held[:50]}, promote=True)
    if holdings_wide and entities:
        add(Block.SECURITY_QUANT, 'quant.securities',
            {'instrument_ids': [entity['instrument_id'] for entity in entities]})

    sections_wanted = any(b in allowed for b in SECTIONS + (Block.COMPANY_DIGEST,))
    digest_mode = (use_digests and sections_wanted and not price_only
                   and Block.COMPANY_DIGEST not in contract.forbidden
                   and not (set(SECTIONS) & set(contract.forbidden)))
    for index, entity in enumerate(entities):
        instrument_id = entity['instrument_id']
        first_ones = index < 2   # required blocks cover at most two entities
        if holdings_wide:
            continue
        if digest_mode:
            block = Block.COMPANY_DIGEST
            allowed.setdefault(block, contract.route)
            add(block, 'research.company_digest',
                {'instrument_id': instrument_id, 'sections': digest_sections(question, decision.primary)},
                first_ones and any(b in contract.required for b in (Block.COMPANY_FACTS, Block.COMPANY_DIGEST)))
        if Block.PRICE_SNAPSHOT in allowed:
            add(Block.PRICE_SNAPSHOT, 'market.latest', {'instrument_id': instrument_id}, first_ones)
        if Block.SECURITY_QUANT in allowed and not price_only and (
                Block.SECURITY_QUANT in contract.required or RISK_WORDS.search(question)):
            add(Block.SECURITY_QUANT, 'quant.security', {'instrument_id': instrument_id}, first_ones,
                promote=bool(RISK_WORDS.search(question)))
        if digest_mode or price_only:
            continue
        for block in SECTIONS:
            if block in allowed:
                add(block, 'research.company_sections',
                    {'instrument_id': instrument_id, 'sections': [block.value],
                     'limit': 20 if block is Block.COMPANY_FACTS else 5,
                     'sector_comparison_limit': 5 if block is Block.SECTOR else 0}, first_ones)

    if Block.EVIDENCE_SEARCH in allowed and not price_only and (portfolio or entities):
        args = {'query': question, 'include_broader_context': True, 'limit': contract.search_limit}
        if entities:
            args['symbols'] = [e['symbol'] for e in entities]
        if portfolio:
            args['portfolio_id'] = portfolio['portfolio_id']
        add(Block.EVIDENCE_SEARCH, 'research.search', args)

    market_asked = 'market_terms' in decision.flags
    if Block.MARKET_SNAPSHOT in allowed and not price_only and (
            Block.MARKET_SNAPSHOT in contract.required or market_asked):
        add(Block.MARKET_SNAPSHOT, 'market.overview',
            {'sections': ['snapshot', 'gainers', 'losers', 'sectors'], 'limit': 5}, promote=market_asked)
    if Block.MARKET_BRIEF in allowed and not price_only and (
            Block.MARKET_BRIEF in contract.required or market_asked):
        add(Block.MARKET_BRIEF, 'research.morning_brief',
            {'symbols': [e['symbol'] for e in entities]} if entities else {}, promote=market_asked)

    cap = min(contract.max_calls, max(0, allowance - FOLLOW_UP_RESERVE))
    kept, budget = enforce_budget(steps, cap)
    for item in budget.missing_required:
        missing.append({'block': item, 'reason': 'budget'})
    calls = [ContentBlock('tool_call', id=f'initial-{n}', name=step.tool, arguments=step.arguments)
             for n, step in enumerate(kept, 1)]
    plan = RoutedPlan(calls, decision, kept, budget, missing)
    log.info('routing primary=%s secondary=%s fallback=%s calls=%d dropped=%d',
             decision.primary.value, [r.value for r in decision.secondary],
             decision.fallback_used, len(calls), len(budget.dropped))
    return plan
