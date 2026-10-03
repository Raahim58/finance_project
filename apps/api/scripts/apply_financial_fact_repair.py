"""Review-only by default. Run from apps/api with the matching deployed code."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.session import SessionLocal
from app.services.financial_fact_repair import apply_reviewed_repair

parser = argparse.ArgumentParser()
parser.add_argument("manifest", type=Path)
parser.add_argument("--apply", action="store_true", help="Commit the reviewed repair transaction")
args = parser.parse_args()
manifest = json.loads(args.manifest.read_text())
with SessionLocal() as db:
    result = apply_reviewed_repair(db, manifest)
    if args.apply:
        db.commit()
    else:
        db.rollback()
    print(json.dumps({**result, "committed": args.apply}))
