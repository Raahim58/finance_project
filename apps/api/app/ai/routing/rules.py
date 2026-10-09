"""Deterministic rule router: question + resolved entities -> route labels.

No model call. A route is a label only; tool choice belongs to the planner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from app.ai.routing.types import Route, RouteDecision, RouterInput
from app.domain.evidence_query import ALTERNATIVES, dividend_query

MIN_SCORE = 2.0            # below this the question is ambiguous -> fallback
SECONDARY_MIN_SCORE = 2.0
MAX_SECONDARY = 2
TIE_MARGIN = 0.5           # top two closer than this -> ambiguous
MIN_TIEBREAK_WORDS = 3     # one-word noise is not worth a model call


def normalize_query(question: str) -> str:
    text = question.replace('’', "'").replace('‘', "'").lower()
    return re.sub(r'\s+', ' ', text).strip()


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


PORTFOLIO = _rx(r"\bmy (portfolio|holdings?|positions?|investments?|stocks|money|allocation)\b|\bi (currently )?(hold|own)\b|\bwhat i (currently )?(hold|own)\b|\bportfolio\b")
IMPACT = _rx(r"\b(affect|impact|hurt|help|mean for|exposure)\b")
REBALANCE = _rx(r"\brebalanc|\bconcentrat|\bdiversif|\btrim\b|\boverweight|\bunderweight|\bbuy more\b|\bsell\b|\bbetter options?\b|\balternatives?\b|\boptions? outside\b|\boutside (of )?(my|the|just)\b|\bother (stocks?|options|names)\b|\bwhat else (should|could|can) i\b|\bnew (stocks?|ideas?)\b|\breduce\b|\bshould i (buy|add)\b|\ballocat|\brecommend|\bwhat (should|can) i do\b|\bnext (step|action)")
PORTFOLIO_REVIEW = _rx(r"\bgoals?\b|what could go wrong|\brisks?\b|\bhow (is|am)\b|what do you think of|\breview\b|\bmandate\b|\bips\b|\bcompliance\b|\bperformance\b")
MARKET = _rx(r"\bmarket\b|\bkse\b|\bindex\b|\bsector\b|\bbreadth\b|\bpsx\b|\bmacro\b|\bmorning\b|\bnews\b")
MARKET_BRIEF = _rx(r"(what'?s|what is) (happening|going on) in the market|\bmarket (today|overview|brief|update|status)\b|\bhow is the market\b|\bmorning brief\b|\bnews today\b")
WHY = _rx(r"\bwhy\b|\bdriver|\bcaused?\b|\breason\b|\bmoving\b|\bmoved\b|\bdown\b|\bup\b")
COMPARE = _rx(r"\bcompare\b|\bversus\b|\bvs\.?\b|\bbetter than\b|\bwhich (is|one)\b")
EARNINGS = _rx(r"\bearnings\b|\beps\b|\bquarter(ly)?\b|\bbeat\b|\bmiss(ed)?\b|\bresults?\b")
UPCOMING = _rx(r"\bupcoming\b|\bpreview\b|\bahead of\b|\bwhat to watch\b|\bexpect\b|\bnext (quarter|result)")
EVENT = _rx(r"\bmerger\b|\bacquisition\b|\bguidance\b|\blaunch\b|\bfiling\b|\bannounce|\bboard meeting\b|\bexpansion\b|\bright shares?\b|\bbonus\b")
TECHNICAL = _rx(r"\brsi\b|\bmacd\b|\bsupport\b|\bresistance\b|\bmoving average\b|\bchart\b|\btechnical\b|\bbreakout\b|\boverbought\b|\boversold\b")
ANALYST = _rx(r"\banalysts?\b|\brating\b|\btarget price\b|\bconsensus\b|\brevisions?\b|\bupgrade\b|\bdowngrade\b")
FUNDAMENTALS = _rx(r"\brevenue\b|\bmargins?\b|\bvaluation\b|\bp/?e\b|\bbalance sheet\b|\bdebt\b|\bcash flow\b|\bfinancials?\b|\bfundamentals?\b|\bdividends?\b|\bbook value\b|\bprofit\b")
DEFINITION_START = _rx(r"^(what is|what are|what's|explain|define|meaning of)\b")
WATCHLIST = _rx(r"\bwatchlist\b|\bwhat should i watch\b|\bwhat changed\b|\bmovers\b|\bgainers\b|\blosers\b")
STOCK_TAKE = _rx(r"going on with|\btake on\b|what do you think|\breview\b|\bprice\b|\bquote\b|\blatest\b|\bupdate\b|tell me about|\boutlook\b")
FOLLOW_UP = _rx(r"^(what about|does that|where did you|and what|and how)\b")
PRICE_ONLY = _rx(r"\b(price|quote|trading at)\b")
NOT_PRICE_ONLY = _rx(r"\b(compare|financial|invest|review|risk|outlook|portfolio|why|earnings)\b")


@dataclass(frozen=True)
class Features:
    text: str
    entities: int
    portfolio_selected: bool
    company_only: bool
    portfolio_words: bool
    market_words: bool

    def has(self, pattern: re.Pattern) -> bool:
        return bool(pattern.search(self.text))


Rule = tuple[Route, float, Callable[[Features], bool]]

RULES: tuple[Rule, ...] = (
    (Route.MARKET_BRIEF, 3.0, lambda f: f.has(MARKET_BRIEF)),
    (Route.MARKET_DRIVER_EXPLAINER, 3.0, lambda f: f.has(WHY) and (f.market_words or f.entities > 0)),
    (Route.SINGLE_STOCK_QUICK_TAKE, 1.5, lambda f: f.entities == 1),
    (Route.SINGLE_STOCK_QUICK_TAKE, 1.0, lambda f: f.entities == 1 and f.has(STOCK_TAKE)),
    (Route.MULTI_STOCK_COMPARE, 1.0, lambda f: f.entities >= 2),
    (Route.MULTI_STOCK_COMPARE, 2.5, lambda f: f.entities >= 2 and f.has(COMPARE)),
    (Route.EARNINGS_REACTION, 2.5, lambda f: f.has(EARNINGS)),
    (Route.EARNINGS_PREVIEW, 3.0, lambda f: f.has(EARNINGS) and f.has(UPCOMING)),
    (Route.EVENT_REACTION, 2.5, lambda f: f.has(EVENT)),
    (Route.TECHNICAL_SETUP, 3.0, lambda f: f.has(TECHNICAL)),
    (Route.ANALYST_SENTIMENT, 3.0, lambda f: f.has(ANALYST)),
    (Route.FUNDAMENTALS_SNAPSHOT, 2.5, lambda f: f.has(FUNDAMENTALS) or dividend_query(f.text)),
    (Route.FUNDAMENTALS_SNAPSHOT, 2.0, lambda f: f.entities > 0 and dividend_query(f.text) and not f.has(REBALANCE) and not f.has(IMPACT)),
    (Route.PORTFOLIO_REVIEW, 3.0, lambda f: f.portfolio_words and f.has(PORTFOLIO_REVIEW)),
    (Route.PORTFOLIO_REVIEW, 1.0, lambda f: f.portfolio_words),
    (Route.PORTFOLIO_IMPACT, 3.5, lambda f: (f.portfolio_words or f.has(_rx(r"\bme\b"))) and f.has(IMPACT) and (f.market_words or f.entities > 0)),
    (Route.PORTFOLIO_IMPACT, 3.0, lambda f: f.portfolio_selected and f.entities > 0 and f.has(_rx(r"\bfit\b|\bworth adding\b"))),
    (Route.PORTFOLIO_REBALANCE, 3.0, lambda f: (f.portfolio_words or f.portfolio_selected) and (f.has(REBALANCE) or f.has(ALTERNATIVES))),
    (Route.WATCHLIST_MONITOR, 3.0, lambda f: f.has(WATCHLIST)),
    (Route.DEFINITION_OR_CONCEPT, 3.5, lambda f: f.has(DEFINITION_START) and f.entities == 0
        and not f.market_words and not f.portfolio_words and not f.has(_rx(r"going on|happening"))),
)


def price_only(question: str) -> bool:
    text = normalize_query(question)
    return bool(PRICE_ONLY.search(text)) and not NOT_PRICE_ONLY.search(text)


def route_query(router_input: RouterInput) -> RouteDecision:
    text = normalize_query(router_input.question)
    features = Features(
        text=text, entities=len(router_input.entity_symbols),
        portfolio_selected=router_input.portfolio_selected and not router_input.company_only,
        company_only=router_input.company_only,
        portfolio_words=bool(PORTFOLIO.search(text)) and not router_input.company_only,
        market_words=bool(MARKET.search(text)))
    scores: dict[Route, float] = {}
    for route, weight, predicate in RULES:
        if predicate(features):
            scores[route] = scores.get(route, 0.0) + weight
    flags = []
    if FOLLOW_UP.search(text):
        flags.append('follow_up')
    if features.market_words:
        flags.append('market_terms')
    if features.entities and price_only(router_input.question):
        flags.append('price_only')
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0].value))
    scores_out = {route.value: round(score, 2) for route, score in ranked}
    if not ranked or ranked[0][1] < MIN_SCORE:
        # Follow-ups lack their antecedent here; a label cannot be recovered from text alone.
        usable = 'follow_up' not in flags and len(text.split()) >= MIN_TIEBREAK_WORDS
        candidates = tuple(r for r in Route if r is not Route.GENERAL_FALLBACK) if usable else ()
        return RouteDecision(Route.GENERAL_FALLBACK, (), 0.0, 'fallback', True, tuple(flags), scores_out,
                             tiebreak_candidates=candidates)
    primary, top = ranked[0]
    secondary = tuple(route for route, score in ranked[1:]
                      if score >= SECONDARY_MIN_SCORE)[:MAX_SECONDARY]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    confidence = round(min(1.0, 0.5 + (top - runner_up) / (2 * top)), 2)
    tied = tuple(route for route, score in ranked if top - score < TIE_MARGIN)
    return RouteDecision(primary, secondary, confidence, 'rules_only', False, tuple(flags), scores_out,
                         tiebreak_candidates=tied if len(tied) > 1 else ())
