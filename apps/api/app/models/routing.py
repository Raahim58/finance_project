"""Queryable routing log and offline router evaluation runs.

Stores route labels and block names only: never question text, evidence or keys.
"""
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def now():
    return datetime.now(UTC)


class RouteDecisionRecord(Base):
    __tablename__ = "route_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("assistant_executions.id"), unique=True)
    primary_route: Mapped[str] = mapped_column(String(40), index=True)
    secondary_routes_json: Mapped[str] = mapped_column(Text, default="[]")
    decision_source: Mapped[str] = mapped_column(String(30))  # rules_only | rules_plus_classifier | fallback
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    flags_json: Mapped[str] = mapped_column(Text, default="[]")
    scores_json: Mapped[str] = mapped_column(Text, default="{}")
    blocks_json: Mapped[str] = mapped_column(Text, default="[]")
    missing_blocks_json: Mapped[str] = mapped_column(Text, default="[]")
    router_version: Mapped[str] = mapped_column(String(40))
    planner_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class RouteBudgetLog(Base):
    __tablename__ = "route_budget_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    route_decision_id: Mapped[str] = mapped_column(ForeignKey("route_decisions.id"), unique=True)
    cap: Mapped[int] = mapped_column(Integer)
    pre_steps: Mapped[int] = mapped_column(Integer)
    post_steps: Mapped[int] = mapped_column(Integer)
    dropped_json: Mapped[str] = mapped_column(Text, default="[]")
    missing_required_json: Mapped[str] = mapped_column(Text, default="[]")


class RoutingEvalRun(Base):
    __tablename__ = "routing_eval_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    eval_case_id: Mapped[str] = mapped_column(String(80))
    router_version: Mapped[str] = mapped_column(String(40))
    mode: Mapped[str] = mapped_column(String(30))  # rules | rules_plus_classifier
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(120))
    expected_primary: Mapped[str] = mapped_column(String(40))
    actual_primary: Mapped[str] = mapped_column(String(40))
    expected_secondary_json: Mapped[str] = mapped_column(Text, default="[]")
    actual_secondary_json: Mapped[str] = mapped_column(Text, default="[]")
    decision_source: Mapped[str] = mapped_column(String(30))
    matched: Mapped[bool] = mapped_column(Boolean)
    errors_json: Mapped[str] = mapped_column(Text, default="[]")
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
