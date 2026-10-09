"""Bounded, resumable monthly OHLCV recovery through the existing pipeline outbox.

Dry-run by default. Constituents come from the latest stored official DPS
capitalization workbook; holdings contribute symbols only, never portfolio IDs.
"""
import argparse
from calendar import monthrange
from datetime import UTC, date, datetime
import json
import time
from sqlalchemy import func, select
from app.db.session import SessionLocal
from app.models.market import Company
from app.models.portfolio import Portfolio, PortfolioHolding
from app.models.workstation import IngestionCoverage, Instrument, MarketObservation
from app.models.pipeline import IngestionStageRun
from app.services.pipeline.runs import VERSION, enqueue, fingerprint
from app.services.instrument_history import history_start


def months_between(start, end):
    if start > end:
        raise ValueError("History start must not follow end")
    cursor = start.replace(day=1)
    while cursor <= end:
        yield cursor
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)


def priority_order(symbols, holdings, constituents):
    holdings, constituents = set(holdings), set(constituents)
    return sorted(set(symbols), key=lambda symbol: (0 if symbol in holdings else 1 if symbol in constituents else 2, symbol))


def covered_month(state, observed_count, month, end, last_observed=None):
    last = date(month.year, month.month, monthrange(month.year, month.month)[1])
    # A terminal status without matching persisted observations is not coverage.
    if not state or state.item_count <= 0 or observed_count < state.item_count or not state.completed_at:
        return False
    if state.status == "complete" and state.completed_at.date() >= last and last <= end:
        return True
    return bool(state.status == "partial" and month <= end < last
                and state.completed_at.date() >= end and last_observed and last_observed >= end)


def plan(db, start, end, *, scope="priority"):
    instruments = list(db.scalars(select(Instrument).join(Company, Company.id == Instrument.company_id)
                                   .where(Company.is_active.is_(True), Instrument.instrument_type == "equity")))
    holdings = set(db.scalars(select(PortfolioHolding.symbol).join(Portfolio, Portfolio.id == PortfolioHolding.portfolio_id)
                             .where(Portfolio.archived_at.is_(None), PortfolioHolding.quantity > 0)))
    latest = db.scalar(select(func.max(MarketObservation.effective_at)).where(MarketObservation.frequency == "capitalization"))
    members = set()
    if latest:
        for observation in db.scalars(select(MarketObservation).where(MarketObservation.frequency == "capitalization",
                                                                      MarketObservation.effective_at == latest)):
            weights = json.loads(observation.values_json).get("index_weights_percent", {})
            if "KSE-100" in weights:
                members.add(observation.instrument_id)
    constituents = {instrument.symbol for instrument in instruments if instrument.id in members}
    if scope == "priority" and not constituents:
        raise ValueError("Stored official KSE-100 membership unavailable; do not substitute guessed constituents")
    by_symbol = {instrument.symbol: instrument for instrument in instruments}
    requested = priority_order(by_symbol, holdings, constituents)
    if scope == "priority":
        requested = [symbol for symbol in requested if symbol in holdings or symbol in constituents]
    elif scope == "remaining":
        requested = [symbol for symbol in requested if symbol not in holdings and symbol not in constituents]
    coverage = {(row.instrument_id, row.period_key): row for row in db.scalars(select(IngestionCoverage)
                .where(IngestionCoverage.dataset_type == "price_history", IngestionCoverage.source == "dps"))}
    # DATE conversion is exchange-local: UTC timestamps are often the preceding day.
    selected = db.execute(select(MarketObservation.instrument_id, MarketObservation.effective_at)
                          .where(MarketObservation.is_selected.is_(True), MarketObservation.frequency == "daily")).all()
    from zoneinfo import ZoneInfo
    dates = {}
    for identifier, stamp in selected:
        day = (stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp).astimezone(ZoneInfo("Asia/Karachi")).date()
        dates.setdefault((identifier, day.strftime("%Y-%m")), set()).add(day)
    rows = []
    for symbol in requested:
        instrument = by_symbol[symbol]
        first = history_start(instrument, start)
        if first > end:
            continue
        missing = [month for month in months_between(first, end)
                   if not covered_month(coverage.get((instrument.id, month.strftime("%Y-%m"))),
                                        len(dates.get((instrument.id, month.strftime("%Y-%m")), set())), month, end,
                                        max(dates.get((instrument.id, month.strftime("%Y-%m")), set()), default=None))]
        if missing:
            rows.append({"symbol": symbol, "instrument_id": instrument.id, "months": missing,
                         "priority": "held" if symbol in holdings else "kse100" if symbol in constituents else "remaining"})
    return rows, {"constituents": len(constituents), "held_symbols": len(holdings), "membership_at": latest,
                  "planned_symbols": len(rows), "planned_months": sum(len(row["months"]) for row in rows)}


def queue_batch(db, rows, *, end):
    counts = {"created": 0, "already_pending": 0, "terminal_unrecovered": 0}
    identifiers = []
    for row in rows:
        for month in row["months"]:
            subject = f"history_price:{row['instrument_id']}:{month}"
            payload = {"symbol": row["symbol"], "year": month.year, "month": month.month}
            # Refresh partial current-month windows once per requested as-of date.
            if month.year == end.year and month.month == end.month:
                payload["as_of"] = str(end)
            before = db.scalar(select(IngestionStageRun.id).where(IngestionStageRun.stage == "history_prices",
                               IngestionStageRun.subject_key == subject,
                               IngestionStageRun.input_hash == fingerprint(payload),
                               IngestionStageRun.code_version == VERSION))
            run = enqueue(db, "history_prices", subject, payload, mode="historical")
            if before is None:
                counts["created"] += 1
            elif run.status in ("queued", "retry_wait", "running"):
                counts["already_pending"] += 1
            else:
                counts["terminal_unrecovered"] += 1
            identifiers.append(run.id)
    db.commit()
    return {**counts, "run_ids": identifiers}


def choose_batch(db, rows, batch_size):
    existing = {(run.subject_key, run.input_hash): run for run in db.scalars(select(IngestionStageRun)
                .where(IngestionStageRun.stage == "history_prices", IngestionStageRun.code_version == VERSION))}
    pending_symbols = {run.input.get("symbol") for run in existing.values()
                       if run.status in ("queued", "retry_wait", "running")}
    pending_count = sum(run.status in ("queued", "retry_wait", "running") for run in existing.values())
    batch, terminal_gaps = [], 0
    for row in rows:
        if row["symbol"] in pending_symbols:
            continue
        available = []
        for month in row["months"]:
            payload = {"symbol": row["symbol"], "year": month.year, "month": month.month}
            if month.year == row["as_of"].year and month.month == row["as_of"].month:
                payload["as_of"] = str(row["as_of"])
            run = existing.get((f"history_price:{row['instrument_id']}:{month}", fingerprint(payload)))
            if run and run.status in ("completed", "dead_letter"):
                terminal_gaps += 1
            else:
                available.append(month)
        if available and len(batch) < batch_size:
            batch.append({**row, "months": available})
    return batch, pending_count, terminal_gaps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2021, 10, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    parser.add_argument("--scope", choices=("priority", "remaining", "all"), default="priority")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--enqueue", action="store_true")
    parser.add_argument("--watch", action="store_true", help="Continue bounded batches until complete or source gaps remain")
    parser.add_argument("--max-in-flight", type=int, default=350)
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 20 or args.max_in_flight < 1 or args.poll_seconds < 30:
        parser.error("Batch size must be 1..20, max in flight positive, polling at least 30 seconds")
    if args.watch and not args.enqueue:
        parser.error("--watch requires --enqueue")
    while True:
        with SessionLocal() as db:
            rows, summary = plan(db, args.start, args.end, scope=args.scope)
            for row in rows:
                row["as_of"] = args.end
            batch, pending, terminal_gaps = choose_batch(db, rows, args.batch_size)
            result = {"scope": args.scope, "start": args.start, "end": args.end, **summary,
                      "batch": [{"symbol": row["symbol"], "months": len(row["months"])} for row in batch],
                      "in_flight": pending, "terminal_month_gaps": terminal_gaps}
            planned = sum(len(row["months"]) for row in batch)
            if args.enqueue and planned and pending + planned <= args.max_in_flight:
                queued = queue_batch(db, batch, end=args.end)
                result["queued"] = {key:value for key,value in queued.items() if key != "run_ids"}
            elif args.enqueue and planned:
                result["status"] = "waiting_for_batch_capacity"
            if args.watch:
                # The shared dispatcher ranks classification/report processing
                # ahead of history. Reserve a small price-only share so it cannot
                # starve, while current live observations retain broker priority.
                from app.services.pipeline.runs import dispatch
                from app.jobs.pipeline_tasks import execute, QUEUES
                result["price_runs_dispatched"] = dispatch(db, lambda identifier,stage,mode:
                    execute.apply_async(args=(identifier,),queue=QUEUES[stage],priority=8),
                    limit=20,scope="history_price")
            print(json.dumps(result, default=str), flush=True)
            if not args.watch:
                return
            if not batch and not pending:
                print(json.dumps({"status":"source_gaps_remain" if rows else "complete", "remaining_months":summary["planned_months"]}), flush=True)
                return
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
