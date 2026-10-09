"""Typed routing contracts. Pure data: no database, provider or tool access."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class Route(str, Enum):
    MARKET_BRIEF = 'market_brief'
    MARKET_DRIVER_EXPLAINER = 'market_driver_explainer'
    SINGLE_STOCK_QUICK_TAKE = 'single_stock_quick_take'
    MULTI_STOCK_COMPARE = 'multi_stock_compare'
    EARNINGS_PREVIEW = 'earnings_preview'
    EARNINGS_REACTION = 'earnings_reaction'
    EVENT_REACTION = 'event_reaction'
    TECHNICAL_SETUP = 'technical_setup'
    ANALYST_SENTIMENT = 'analyst_sentiment'
    FUNDAMENTALS_SNAPSHOT = 'fundamentals_snapshot'
    PORTFOLIO_REVIEW = 'portfolio_review'
    PORTFOLIO_IMPACT = 'portfolio_impact'
    PORTFOLIO_REBALANCE = 'portfolio_rebalance'
    WATCHLIST_MONITOR = 'watchlist_monitor'
    DEFINITION_OR_CONCEPT = 'definition_or_concept'
    GENERAL_FALLBACK = 'general_fallback'


class Block(str, Enum):
    """Evidence block types. Each maps to exactly one existing read tool or is
    declared unavailable so the answer must state that data is missing."""
    PRICE_SNAPSHOT = 'price_snapshot'            # market.latest (SQL prices)
    COMPANY_DIGEST = 'company_digest'            # research.company_digest
    COMPANY_FACTS = 'company_facts'              # research.company_sections
    SECTOR = 'sector'
    MARKET_RISK = 'market_risk'
    EVENTS = 'events'
    PORTFOLIO_SNAPSHOT = 'portfolio_snapshot'    # portfolio.summary (ownership-checked SQL)
    IPS_COMPLIANCE = 'ips_compliance'            # ips.compliance
    PORTFOLIO_QUANT = 'portfolio_quant'          # quant.portfolio
    EVIDENCE_SEARCH = 'evidence_search'          # research.search (document text only)
    MARKET_UNIVERSE = 'market_universe'          # market.universe ranked by stored screening score
    MARKET_SNAPSHOT = 'market_snapshot'          # market.overview (SQL index/movers/sectors)
    MARKET_BRIEF = 'market_brief'                # research.morning_brief (commentary, never exact numbers)
    PORTFOLIO_PERFORMANCE = 'portfolio_performance'  # portfolio.performance (ledger history)
    PORTFOLIO_EVENTS = 'portfolio_events'        # portfolio.event_exposure (events mapped to holdings)
    SECURITY_QUANT = 'security_quant'            # quant.security (per-instrument return/risk)
    # No backing tool today. Planned as explicit gaps, never invented.
    TECHNICAL_LEVELS = 'technical_levels'
    ANALYST_REVISIONS = 'analyst_revisions'
    EARNINGS_CALENDAR = 'earnings_calendar'


UNAVAILABLE_BLOCKS = frozenset({Block.TECHNICAL_LEVELS, Block.ANALYST_REVISIONS, Block.EARNINGS_CALENDAR})
PORTFOLIO_BLOCKS = frozenset({Block.PORTFOLIO_SNAPSHOT, Block.IPS_COMPLIANCE, Block.PORTFOLIO_QUANT,
                              Block.PORTFOLIO_PERFORMANCE, Block.PORTFOLIO_EVENTS})


@dataclass(frozen=True)
class RouterInput:
    question: str
    entity_symbols: tuple[str, ...] = ()
    portfolio_selected: bool = False
    company_only: bool = False


@dataclass(frozen=True)
class RouteDecision:
    primary: Route
    secondary: tuple[Route, ...] = ()
    confidence: float = 0.0
    decision_source: str = 'rules_only'   # rules_only | rules_plus_classifier | fallback
    fallback_used: bool = False
    flags: tuple[str, ...] = ()
    scores: dict[str, float] = field(default_factory=dict)
    router_version: str = 'rule-router.v1'
    # Routes the rules could not separate; only these (or all, on no hit) may be
    # offered to the tie-break classifier.
    tiebreak_candidates: tuple[Route, ...] = ()

    def to_dict(self) -> dict:
        data = asdict(self)
        data['primary'] = self.primary.value
        data['secondary'] = [route.value for route in self.secondary]
        data['tiebreak_candidates'] = [route.value for route in self.tiebreak_candidates]
        return data


@dataclass(frozen=True)
class RetrievalContract:
    """Fixed evidence policy for one route. Order of `blocks` is assembly order."""
    route: Route
    required: tuple[Block, ...]
    optional: tuple[Block, ...] = ()
    forbidden: tuple[Block, ...] = ()
    # Blocks this route contributes when it is only a secondary route.
    as_secondary: tuple[Block, ...] = ()
    portfolio_context: str = 'if_selected'   # always | if_selected | never
    entity_blocks: bool = True               # per-entity blocks allowed
    max_entities: int = 5
    max_calls: int = 12                      # hard cap on initial tool calls
    search_limit: int = 5
    primary_only: bool = False


@dataclass(frozen=True)
class PlanStep:
    block: Block
    tool: str
    arguments: dict
    required: bool
    source_route: Route
    priority: int  # lower survives budget enforcement longer


@dataclass
class BudgetLog:
    cap: int
    pre_steps: int
    post_steps: int
    dropped: list[dict] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
