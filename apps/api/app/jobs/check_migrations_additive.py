"""Fail unless every pending Alembic revision is additive.

Ingestion workers keep running old code during a deploy, so a pending migration may
only add things. Destructive/changing operations need ALLOW_BREAKING_MIGRATION=1.

  python -m app.jobs.check_migrations_additive
"""
import os
import re
import sys
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

BREAKING = re.compile(
    r"op\.(drop_table|drop_column|drop_index|drop_constraint|rename_table|alter_column|"
    r"drop_index|execute\s*\(\s*[\"'](?:DROP|ALTER TABLE [^\"']* (?:DROP|RENAME|ALTER COLUMN)|TRUNCATE|DELETE))",
    re.I)


def breaking_ops(source: str) -> list[str]:
    # Only the upgrade body matters: downgrade() is expected to drop things.
    return [m.group(1).lower() for m in BREAKING.finditer(source.split("def downgrade", 1)[0])]


def pending_breaking(script: ScriptDirectory, current: str | None) -> list[tuple[str, str]]:
    found = []
    for revision in script.iterate_revisions("heads", current or "base"):
        if current and revision.revision == current:
            continue
        found.extend((revision.revision, op) for op in breaking_ops(Path(revision.path).read_text()))
    return found


def load_script() -> ScriptDirectory:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return ScriptDirectory.from_config(config)


def main() -> int:
    from app.db.session import engine
    script = load_script()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    offenders = pending_breaking(script, current)
    if not offenders:
        print(f"pending migrations are additive (current={current})")
        return 0
    for revision, operation in offenders:
        print(f"non-additive migration {revision}: {operation}", file=sys.stderr)
    if os.environ.get("ALLOW_BREAKING_MIGRATION") == "1":
        print("ALLOW_BREAKING_MIGRATION=1: proceeding with running workers on old code", file=sys.stderr)
        return 0
    print("Refusing: old-code workers are running. Make it additive (expand/contract) or "
          "set ALLOW_BREAKING_MIGRATION=1 after coordinating.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
