"""The schema baseline keeps the last deployed revision; older upgrades use Git history."""
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError

BASELINE_REVISION = "0039_ai_briefs"
LEGACY_SOURCE_COMMIT = "e7046f77278619de1d83bf23b709d66eb74d255a"


def require_supported_revision(script: ScriptDirectory, revision: str | None) -> None:
    if revision is None:
        return
    try:
        script.revision_map.get_revision(revision)
    except ResolutionError as exc:
        raise RuntimeError(
            f"Database revision {revision!r} predates or is outside this migration chain. "
            f"For a pre-baseline database, use source commit {LEGACY_SOURCE_COMMIT} "
            f"to run alembic upgrade {BASELINE_REVISION}, then use this checkout. "
            "Do not stamp an older database: historical data transformations must run."
        ) from exc
