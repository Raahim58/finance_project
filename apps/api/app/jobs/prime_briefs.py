"""Queue AI briefs for a user's portfolio holdings. Dry run unless --apply is passed.

Uses the user's saved, active LLM key (same path as opening the pages). Queues:
  1. company digests (the company page brief) for every holding;
  2. one event-explanation batch for the portfolio (max 8 holdings, 16 calls).
"""
import argparse, uuid
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.user import User
from app.schemas.research_intelligence import BatchRequest
from app.services.research_job_service import generation_config, preview_batch, enqueue_batch, selected_companies
from app.services.company_digest_service import read_digest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--email", required=True)
    ap.add_argument("--portfolio-id", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == a.email))
        if not user: raise SystemExit("No such user")
        if not generation_config(db, user):
            raise SystemExit("No active LLM key saved for this user; add one in Settings first.")
        req = BatchRequest(client_request_id="prime-" + uuid.uuid4().hex[:12], portfolio_id=a.portfolio_id)
        companies = selected_companies(db, user, req)
        print("Holdings:", ", ".join(c.symbol for c in companies))
        print("Event-explanation preview:", preview_batch(db, user, req))
        if not a.apply:
            print("Dry run only. Re-run with --apply to queue the briefs."); return
        for c in companies:
            out = read_digest(db, user, c, active=True)
            print(f"digest {c.symbol}: {out['status']}")
        db.commit()
        print("Batch:", enqueue_batch(db, user, req))
        db.commit()


if __name__ == "__main__":
    main()
