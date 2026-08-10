from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workstation import ExchangeCalendarDay


@dataclass(frozen=True, slots=True)
class SessionDay:
    session_date: date
    is_session: bool
    status: str
    reason: str | None = None


def session_day(db: Session, day: date, exchange_code: str = "PSX") -> SessionDay:
    explicit = db.scalar(
        select(ExchangeCalendarDay).where(
            ExchangeCalendarDay.exchange_code == exchange_code,
            ExchangeCalendarDay.session_date == day,
        )
    )
    if explicit:
        return SessionDay(day, explicit.is_session, explicit.status, explicit.reason)
    if day.weekday() >= 5:
        return SessionDay(day, False, "calendar_rule", "Weekend")
    # This is deliberately marked assumed. Jobs and analytics can distinguish
    # it from an exchange-published session/closure instead of treating weekday
    # logic as authoritative holiday knowledge.
    return SessionDay(day, True, "assumed_weekday", "No explicit PSX calendar record")


def sessions_between(db: Session, start: date, end: date, exchange_code: str = "PSX") -> list[SessionDay]:
    if end < start:
        raise ValueError("end must not precede start")
    days = []
    cursor = start
    while cursor <= end:
        candidate = session_day(db, cursor, exchange_code)
        if candidate.is_session:
            days.append(candidate)
        cursor += timedelta(days=1)
    return days


def upsert_calendar_day(
    db: Session,
    *,
    session_date: date,
    is_session: bool,
    reason: str | None,
    artifact_id: str | None,
    exchange_code: str = "PSX",
    status: str = "observed",
) -> ExchangeCalendarDay:
    row = db.scalar(
        select(ExchangeCalendarDay).where(
            ExchangeCalendarDay.exchange_code == exchange_code,
            ExchangeCalendarDay.session_date == session_date,
        )
    )
    if row is None:
        row = ExchangeCalendarDay(exchange_code=exchange_code, session_date=session_date, is_session=is_session)
    row.is_session = is_session
    row.reason = reason
    row.artifact_id = artifact_id
    row.status = status
    db.add(row)
    db.flush()
    return row
