import argparse
import json

from app.db.session import SessionLocal
from app.services.company_event_service import relink_stored_news


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild company links from already-stored news text without network access"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the deterministic replacement links; default is a dry run",
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        print(json.dumps(relink_stored_news(db, apply=args.apply), sort_keys=True))


if __name__ == "__main__":
    main()
