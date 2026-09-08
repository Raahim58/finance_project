"""One typed execution plan for evidence coverage and spending limits."""
import re
from dataclasses import dataclass
from typing import Literal

MARKET = re.compile(r"market.wide|across (?:the )?(?:PSX|market)|PSX market|what stocks|which stocks|whole market", re.I)
ALLOCATION = re.compile(r"how much|\bbuy\b|\bsell\b|\bswitch\b|\bsize\b|\ballocat|worth adding|should I add|recommend|what (?:should|can) i do", re.I)
COMPARISON = re.compile(r"\bcompare\b|\bversus\b|\bvs\b|\bor\b", re.I)


@dataclass(frozen=True)
class ExecutionPlan:
    kind: Literal["factual", "allocation", "market_wide"]
    mode: Literal["targeted", "sizing", "comparison", "market_wide"]
    call_input: int
    execution_input: int
    deadline_seconds: int


def classify(question: str, has_security=False, named_count=0) -> ExecutionPlan:
    if not has_security and MARKET.search(question):
        return ExecutionPlan("market_wide", "market_wide", 40_000, 200_000, 300)
    kind = "allocation" if ALLOCATION.search(question) else "factual"
    if named_count > 1 or COMPARISON.search(question):
        return ExecutionPlan(kind, "comparison", 40_000, 160_000, 180)
    if kind == "allocation" or has_security:
        return ExecutionPlan(kind, "sizing", 20_000, 80_000, 180)
    return ExecutionPlan(kind, "targeted", 20_000, 48_000, 120)
