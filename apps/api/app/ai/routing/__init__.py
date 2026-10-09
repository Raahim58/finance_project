"""Deterministic query routing: question -> route label -> retrieval contract -> plan."""
from app.ai.routing.planner import RoutedPlan, plan_initial_evidence  # noqa: F401
from app.ai.routing.rules import route_query  # noqa: F401
from app.ai.routing.types import Route, RouteDecision, RouterInput  # noqa: F401
