"""Explicit demo preparation; defaults to read-only preview."""

import argparse
import json
from uuid import uuid4
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.user import User
from app.models.portfolio import Portfolio
from app.schemas.research_intelligence import BatchRequest
from app.services.research_job_service import preview_batch, enqueue_batch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-email", required=True)
    parser.add_argument("--portfolio", default="default")
    parser.add_argument("--enqueue", action="store_true")
    parser.add_argument("--request-id", default=None)
    parser.add_argument("--max-calls", type=int, default=16)
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.user_email))
        if user is None:
            raise SystemExit("User not found")
        portfolio = (
            db.scalar(
                select(Portfolio).where(
                    Portfolio.user_id == user.id,
                    Portfolio.is_default.is_(True),
                    Portfolio.archived_at.is_(None),
                )
            )
            if args.portfolio == "default"
            else db.get(Portfolio, args.portfolio)
        )
        if portfolio is None or portfolio.user_id != user.id:
            raise SystemExit("Portfolio not found")
        request = BatchRequest(
            client_request_id=args.request_id or str(uuid4()),
            portfolio_id=portfolio.id,
            max_calls=args.max_calls,
        )
        result = (
            enqueue_batch(db, user, request) if args.enqueue else preview_batch(db, user, request)
        )
        print(json.dumps(result, default=str, indent=2))


if __name__ == "__main__":
    main()
