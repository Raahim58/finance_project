"""Coordinate ingestion writes without serializing upstream HTTP requests."""

from sqlalchemy import text


def lock_ingestion_writes(db, scope: str) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:scope))"), {"scope": scope})
