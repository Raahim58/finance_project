"""Routing eval set: expected labels for fixed questions (no live data needed)."""
from __future__ import annotations

from dataclasses import dataclass

from app.ai.routing.types import Route as R


@dataclass(frozen=True)
class RoutingEvalCase:
    id: str
    question: str
    symbols: tuple[str, ...]
    portfolio_selected: bool
    primary: R
    secondary: tuple[R, ...] = ()   # expected to be a subset of the actual secondaries


def _c(id, question, symbols, selected, primary, secondary=()):
    return RoutingEvalCase(id, question, tuple(symbols), selected, primary, tuple(secondary))


ROUTING_EVAL: tuple[RoutingEvalCase, ...] = (
    _c('market-brief', "What's happening in the market today?", (), False, R.MARKET_BRIEF),
    _c('market-impact', "What’s happening in the market, and how does it affect me?", (), True, R.PORTFOLIO_IMPACT, (R.MARKET_BRIEF,)),
    _c('market-driver', 'Why did the market fall?', (), False, R.MARKET_DRIVER_EXPLAINER),
    _c('stock-price', 'What is LUCK latest price?', ('LUCK',), False, R.SINGLE_STOCK_QUICK_TAKE),
    _c('compare', 'Compare LUCK and FFC', ('LUCK', 'FFC'), False, R.MULTI_STOCK_COMPARE),
    _c('earn-preview', 'What to watch before LUCK earnings, upcoming results', ('LUCK',), False, R.EARNINGS_PREVIEW),
    _c('earn-reaction', 'LUCK earnings beat estimates', ('LUCK',), False, R.EARNINGS_REACTION),
    _c('event', 'LUCK announced a merger, what now?', ('LUCK',), False, R.EVENT_REACTION),
    _c('technical', 'Is LUCK RSI overbought, where is support?', ('LUCK',), False, R.TECHNICAL_SETUP),
    _c('analyst', 'Any analyst upgrade or target price change for LUCK?', ('LUCK',), False, R.ANALYST_SENTIMENT),
    _c('fundamentals', 'How are LUCK margins and debt?', ('LUCK',), False, R.FUNDAMENTALS_SNAPSHOT),
    _c('pf-review', 'What do you think of my portfolio right now?', (), True, R.PORTFOLIO_REVIEW),
    _c('pf-goals', 'Can my portfolio meet my goals?', (), True, R.PORTFOLIO_REVIEW),
    _c('pf-better', 'Are there better options than what I currently hold?', (), True, R.PORTFOLIO_REBALANCE),
    _c('pf-rebalance', 'Should I rebalance to reduce concentration?', (), True, R.PORTFOLIO_REBALANCE),
    _c('pf-allocation', 'Recommend and verify allocation', (), True, R.PORTFOLIO_REBALANCE),
    _c('pf-next', 'What should I do next?', (), True, R.PORTFOLIO_REBALANCE),
    _c('watchlist', 'Show my watchlist movers', (), False, R.WATCHLIST_MONITOR),
    _c('define-pe', 'What is a P/E ratio?', (), False, R.DEFINITION_OR_CONCEPT),
    _c('define-yield', 'Explain dividend yield', (), False, R.DEFINITION_OR_CONCEPT),
    _c('noise', 'hmm', (), False, R.GENERAL_FALLBACK),
    _c('follow-up', 'Does that change your view?', (), True, R.GENERAL_FALLBACK),
    # The ten ordinary prompts used in the live evidence suite (entities as resolved there).
    _c('live-1', 'What do you think of my portfolio right now?', (), True, R.PORTFOLIO_REVIEW),
    _c('live-2', 'Should I buy more LUCK or FFC?', ('LUCK', 'FFC'), True, R.PORTFOLIO_REBALANCE),
    _c('live-3', 'Can my portfolio meet my goals?', (), True, R.PORTFOLIO_REVIEW),
    _c('live-4', "What’s happening in the market, and how does it affect me?", (), True, R.PORTFOLIO_IMPACT),
    _c('live-5', 'Why has LUCK been moving lately?', ('LUCK',), True, R.MARKET_DRIVER_EXPLAINER),
    _c('live-6', 'What could go wrong with my investments?', (), True, R.PORTFOLIO_REVIEW),
    _c('live-7', 'Are there better options than what I currently hold?', (), True, R.PORTFOLIO_REBALANCE),
    _c('live-8', 'What about dividends?', ('LUCK', 'FFC'), True, R.FUNDAMENTALS_SNAPSHOT),
    _c('live-9', 'Does that change your view?', ('LUCK', 'FFC'), True, R.GENERAL_FALLBACK),
    _c('live-10', 'Where did you get that number?', ('LUCK', 'FFC'), True, R.GENERAL_FALLBACK),
    # Deliberately vague: rules cannot separate these, so the classifier is exercised.
    _c('vague-1', 'How are LUCK and FFC doing these days?', ('LUCK', 'FFC'), False, R.MULTI_STOCK_COMPARE),
    _c('vague-2', 'Is now a good time to be invested in cement?', (), False, R.MARKET_DRIVER_EXPLAINER),
    _c('vague-3', 'Tell me whether the central bank decision matters for banks', (), False, R.MARKET_DRIVER_EXPLAINER),
    _c('vague-4', 'Anything I should know about MEBL this week?', ('MEBL',), False, R.SINGLE_STOCK_QUICK_TAKE),
)
