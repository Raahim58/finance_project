"""Delete every saved assistant chat. Dry run unless --apply is passed.

Tables are discovered from the SQLAlchemy foreign keys, so nothing is hard-coded:
rows that must exist only with a chat are deleted, nullable references are set to NULL.
"""
import argparse
from sqlalchemy import delete, func, select, update
import app.models  # noqa: F401  (registers every table)
from app.db.session import Base, SessionLocal

ROOT = "assistant_conversations"


def plan():
    purge = {ROOT}
    changed = True
    while changed:
        changed = False
        for table in Base.metadata.sorted_tables:
            if table.name in purge:
                continue
            for fk in table.foreign_keys:
                if fk.column.table.name in purge and not fk.parent.nullable:
                    purge.add(table.name); changed = True; break
    nullify = [(t, fk.parent) for t in Base.metadata.sorted_tables if t.name not in purge
               for fk in t.foreign_keys if fk.column.table.name in purge and fk.parent.nullable]
    order = [t for t in reversed(Base.metadata.sorted_tables) if t.name in purge]
    return order, nullify


def run(apply):
    order, nullify = plan()
    with SessionLocal() as db:
        for table, column in nullify:
            n = db.scalar(select(func.count()).select_from(table).where(column.is_not(None)))
            print(f"{'set NULL' if apply else 'would null'}: {table.name}.{column.name} ({n} rows)")
            if apply and n:
                db.execute(update(table).where(column.is_not(None)).values({column.name: None}))
        for table in order:
            n = db.scalar(select(func.count()).select_from(table))
            print(f"{'delete' if apply else 'would delete'}: {table.name} ({n} rows)")
            if apply and n:
                db.execute(delete(table))
        if apply:
            db.commit(); print("Done.")
        else:
            db.rollback(); print("Dry run only. Re-run with --apply to delete.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    run(ap.parse_args().apply)
