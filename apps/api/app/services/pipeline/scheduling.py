"""One scheduler owns bounded source polling; 30-second ticks only dispatch work."""
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.models.workstation import ExchangeCalendarDay

KARACHI=ZoneInfo('Asia/Karachi')
NEWS_HOURS=(10,14,21)
# https://www.psx.com.pk/psx/exchange/general/trading-hours (verified 2026-10-06).
REGULAR=(('09:32','15:30'),)
FRIDAY=(('09:17','12:00'),('14:32','16:30'))
PRICE_INTERVAL_MINUTES = 60

def session_windows(db, day):
    explicit=db.scalar(select(ExchangeCalendarDay).where(ExchangeCalendarDay.exchange_code=='PSX',ExchangeCalendarDay.session_date==day))
    if explicit and not explicit.is_session: return [],explicit.status
    if day.weekday()>=5: return [],'weekend'
    if explicit and explicit.session_windows:
        return explicit.session_windows,explicit.status
    if explicit and explicit.open_time and explicit.close_time:
        # A legacy Friday open/close pair cannot represent its midday break.
        if day.weekday()==4: return list(FRIDAY),'regular_schedule_with_calendar'
        return [(explicit.open_time,explicit.close_time)],explicit.status
    return list(FRIDAY if day.weekday()==4 else REGULAR),'regular_schedule_calendar_unverified'

def price_bucket(db,now):
    local=now.astimezone(KARACHI)
    windows,basis=session_windows(db,local.date())
    for opened,closed in windows:
        start=datetime.combine(local.date(),time.fromisoformat(opened),tzinfo=KARACHI)
        end=datetime.combine(local.date(),time.fromisoformat(closed),tzinfo=KARACHI)
        if start<=local<end:
            bucket=start+timedelta(minutes=PRICE_INTERVAL_MINUTES*int((local-start).total_seconds()//(PRICE_INTERVAL_MINUTES*60)))
            return bucket.isoformat(),basis
    return None,basis

def scheduled_bucket(schedule,now,db):
    local=now.astimezone(KARACHI)
    if schedule=='prices': return price_bucket(db,now)[0]
    if schedule=='market_daily':
        from app.jobs.market_daily import target_day
        # The pipeline owns the daily catch-up as well as intraday prices.
        return target_day(now).isoformat()
    hours=NEWS_HOURS if schedule=='news' else (18,) if schedule=='announcements' else (2,) if schedule=='maintenance' else (9,) if schedule=='briefing' else ()
    if not hours: raise ValueError('unknown_source_schedule')
    buckets=[datetime.combine(local.date(),time(hour),tzinfo=KARACHI) for hour in hours]
    due=[b for b in buckets if b<=local]
    if due: return due[-1].isoformat()
    # One catch-up bucket, not every missed run. Prices never catch up at night.
    return datetime.combine(local.date()-timedelta(days=1),time(hours[-1]),tzinfo=KARACHI).isoformat()
