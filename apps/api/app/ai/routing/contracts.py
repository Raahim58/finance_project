"""Retrieval contract registry: the fixed evidence shape allowed for each route.

Assembly order is the order of `required` then `optional`. Anything not listed
is not fetched in the first pass; anything in `forbidden` is removed even when a
secondary route asks for it.
"""
from __future__ import annotations

from app.ai.routing.types import Block, RetrievalContract, Route

B = Block
SECTIONS = (B.COMPANY_FACTS, B.SECTOR, B.MARKET_RISK, B.EVENTS)

CONTRACTS: dict[Route, RetrievalContract] = {c.route: c for c in (
    # Exact market numbers come from SQL (market.overview); the brief is commentary only.
    RetrievalContract(Route.MARKET_BRIEF, required=(B.MARKET_SNAPSHOT, B.MARKET_BRIEF),
        forbidden=SECTIONS + (B.COMPANY_DIGEST, B.EVIDENCE_SEARCH),
        as_secondary=(B.MARKET_SNAPSHOT, B.MARKET_BRIEF),
        portfolio_context='never', entity_blocks=False, max_calls=3),
    RetrievalContract(Route.MARKET_DRIVER_EXPLAINER, required=(B.MARKET_SNAPSHOT, B.MARKET_BRIEF),
        optional=(B.PRICE_SNAPSHOT, B.EVENTS, B.EVIDENCE_SEARCH),
        forbidden=(B.COMPANY_DIGEST, B.COMPANY_FACTS), max_entities=2, max_calls=6),
    RetrievalContract(Route.SINGLE_STOCK_QUICK_TAKE, required=(B.PRICE_SNAPSHOT, B.EVIDENCE_SEARCH),
        optional=(B.SECURITY_QUANT, B.COMPANY_DIGEST) + SECTIONS, forbidden=(B.PORTFOLIO_QUANT,),
        as_secondary=(B.PRICE_SNAPSHOT,), max_entities=1, max_calls=8),
    RetrievalContract(Route.MULTI_STOCK_COMPARE, required=(B.PRICE_SNAPSHOT, B.SECURITY_QUANT, B.EVIDENCE_SEARCH),
        optional=(B.COMPANY_DIGEST,) + SECTIONS, forbidden=(B.PORTFOLIO_QUANT,),
        max_entities=4, max_calls=12),
    RetrievalContract(Route.EARNINGS_PREVIEW,
        required=(B.EARNINGS_CALENDAR, B.PRICE_SNAPSHOT, B.EVENTS),
        optional=(B.COMPANY_FACTS, B.EVIDENCE_SEARCH), forbidden=(B.PORTFOLIO_QUANT,),
        max_entities=2, max_calls=8),
    RetrievalContract(Route.EARNINGS_REACTION,
        required=(B.PRICE_SNAPSHOT, B.COMPANY_FACTS, B.EVENTS),
        optional=(B.EVIDENCE_SEARCH, B.ANALYST_REVISIONS), forbidden=(B.PORTFOLIO_QUANT,),
        max_entities=2, max_calls=8),
    RetrievalContract(Route.EVENT_REACTION, required=(B.EVENTS, B.PRICE_SNAPSHOT),
        optional=(B.EVIDENCE_SEARCH, B.COMPANY_FACTS), forbidden=(B.PORTFOLIO_QUANT, B.COMPANY_DIGEST),
        as_secondary=(B.EVENTS,), max_entities=2, max_calls=8),
    RetrievalContract(Route.TECHNICAL_SETUP, required=(B.TECHNICAL_LEVELS, B.PRICE_SNAPSHOT),
        forbidden=SECTIONS + (B.COMPANY_DIGEST, B.EVIDENCE_SEARCH, B.MARKET_BRIEF),
        portfolio_context='never', max_entities=2, max_calls=3),
    RetrievalContract(Route.ANALYST_SENTIMENT, required=(B.ANALYST_REVISIONS, B.PRICE_SNAPSHOT),
        optional=(B.EVIDENCE_SEARCH, B.EVENTS), forbidden=(B.PORTFOLIO_QUANT, B.COMPANY_DIGEST),
        max_entities=2, max_calls=6),
    RetrievalContract(Route.FUNDAMENTALS_SNAPSHOT,
        required=(B.COMPANY_FACTS, B.PRICE_SNAPSHOT, B.EVIDENCE_SEARCH),
        optional=(B.SECTOR, B.MARKET_RISK, B.EVENTS), forbidden=(B.PORTFOLIO_QUANT,),
        as_secondary=(B.COMPANY_FACTS,), max_entities=2, max_calls=10),
    RetrievalContract(Route.PORTFOLIO_REVIEW,
        required=(B.PORTFOLIO_SNAPSHOT, B.IPS_COMPLIANCE, B.PORTFOLIO_QUANT, B.EVIDENCE_SEARCH),
        optional=(B.PORTFOLIO_PERFORMANCE, B.PRICE_SNAPSHOT, B.COMPANY_DIGEST, B.EVENTS),
        forbidden=(B.MARKET_BRIEF, B.MARKET_SNAPSHOT),
        portfolio_context='always', max_entities=3, max_calls=12, primary_only=True),
    RetrievalContract(Route.PORTFOLIO_IMPACT,
        required=(B.PORTFOLIO_SNAPSHOT, B.IPS_COMPLIANCE, B.EVIDENCE_SEARCH),
        optional=(B.PORTFOLIO_QUANT, B.MARKET_SNAPSHOT, B.MARKET_BRIEF, B.PRICE_SNAPSHOT, B.COMPANY_DIGEST) + SECTIONS,
        portfolio_context='always', max_entities=3, max_calls=12, primary_only=True),
    RetrievalContract(Route.PORTFOLIO_REBALANCE,
        required=(B.PORTFOLIO_SNAPSHOT, B.IPS_COMPLIANCE, B.PORTFOLIO_QUANT, B.SECURITY_QUANT),
        optional=(B.PRICE_SNAPSHOT, B.COMPANY_DIGEST, B.SECTOR, B.EVIDENCE_SEARCH, B.PORTFOLIO_PERFORMANCE,
                  B.MARKET_UNIVERSE),
        forbidden=(B.MARKET_BRIEF, B.MARKET_SNAPSHOT), portfolio_context='always', max_entities=3, max_calls=14,
        primary_only=True),
    RetrievalContract(Route.WATCHLIST_MONITOR, required=(B.MARKET_SNAPSHOT,),
        optional=(B.MARKET_BRIEF, B.PRICE_SNAPSHOT, B.EVENTS), forbidden=(B.COMPANY_DIGEST, B.PORTFOLIO_QUANT),
        max_entities=3, max_calls=6),
    RetrievalContract(Route.DEFINITION_OR_CONCEPT, required=(),
        portfolio_context='never', entity_blocks=False, max_calls=0),
    RetrievalContract(Route.GENERAL_FALLBACK, required=(),
        optional=(B.PRICE_SNAPSHOT, B.EVIDENCE_SEARCH, B.MARKET_BRIEF),
        forbidden=(B.COMPANY_DIGEST, B.PORTFOLIO_QUANT, B.MARKET_SNAPSHOT) + SECTIONS,
        max_entities=2, max_calls=6, search_limit=3),
)}

assert set(CONTRACTS) == set(Route), 'every route needs a retrieval contract'
