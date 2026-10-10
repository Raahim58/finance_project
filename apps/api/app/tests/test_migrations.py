import os
import io
import tarfile

import pytest
import sqlalchemy as sa
from app.db.migration_history import BASELINE_REVISION, LEGACY_SOURCE_COMMIT
import sqlite3
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


API_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SCRIPT = None


@pytest.fixture(scope="module", autouse=True)
def legacy_history(tmp_path_factory):
    """Exercise retired data transformations from immutable Git history, not live revisions."""
    global LEGACY_SCRIPT
    destination = tmp_path_factory.mktemp("legacy-migrations")
    result = subprocess.run(["git", "archive", LEGACY_SOURCE_COMMIT, "apps/api/alembic"], cwd=API_ROOT.parents[1], capture_output=True)
    if result.returncode != 0:
        pytest.fail("Migration parity tests require the pinned pre-squash Git commit.")
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        archive.extractall(destination, filter="data")
    LEGACY_SCRIPT = destination / "apps/api/alembic"


def test_revision_identifiers_fit_default_alembic_version_column() -> None:
    config = Config()
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    revisions = ScriptDirectory.from_config(config).walk_revisions()
    assert all(len(revision.revision) <= 32 for revision in revisions)


def schema_signature(database_url):
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        result = {}
        for table in sorted(set(inspector.get_table_names()) - {"alembic_version"}):
            result[table] = {
                "columns": sorted((column["name"], str(column["type"]), column["nullable"], column["default"])
                                  for column in inspector.get_columns(table)),
                "primary_key": inspector.get_pk_constraint(table),
                "foreign_keys": sorted(inspector.get_foreign_keys(table), key=lambda row: str(row["constrained_columns"])),
                "unique": sorted(inspector.get_unique_constraints(table), key=lambda row: str(row["column_names"])),
                "checks": sorted(inspector.get_check_constraints(table), key=lambda row: str(row["name"])),
                "indexes": [(row["name"], row["column_names"], row["unique"],
                             {key: str(value) for key, value in row.get("dialect_options", {}).items()})
                            for row in sorted(inspector.get_indexes(table), key=lambda row: row["name"])],
            }
        return result
    finally:
        engine.dispose()


def test_single_frozen_baseline_matches_the_original_chain_and_round_trips(tmp_path):
    legacy_url = f"sqlite:///{tmp_path / 'legacy.sqlite'}"
    fresh_url = f"sqlite:///{tmp_path / 'fresh.sqlite'}"
    _legacy_alembic(legacy_url, "head")
    _alembic(fresh_url, "head")
    expected = schema_signature(legacy_url)
    assert len(expected) == 102
    assert schema_signature(fresh_url) == expected
    script = ScriptDirectory.from_config(Config(str(API_ROOT / "alembic.ini")))
    assert [row.revision for row in script.walk_revisions()] == [BASELINE_REVISION]
    _alembic(fresh_url, "base", "downgrade", allow_drop=True)
    assert schema_signature(fresh_url) == {}
    _alembic(fresh_url, "head")
    assert schema_signature(fresh_url) == expected


def test_baseline_downgrade_requires_explicit_destructive_opt_in(tmp_path):
    url = f"sqlite:///{tmp_path / 'guard.sqlite'}"
    _alembic(url, "head")
    before = schema_signature(url)
    with pytest.raises(subprocess.CalledProcessError) as error:
        _alembic(url, "base", "downgrade")
    assert "allow_baseline_drop" in error.value.stderr
    assert schema_signature(url) == before


def test_older_database_is_rejected_without_schema_or_data_writes(tmp_path):
    path = tmp_path / "older.sqlite"
    url = f"sqlite:///{path}"
    _legacy_alembic(url, "0035_pipeline_text_index")
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO users(id,email,password_hash,is_active,created_at,updated_at) VALUES('retained','owner@example.test','encrypted-placeholder',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
    before = path.read_bytes()
    with pytest.raises(subprocess.CalledProcessError) as error:
        _alembic(url, "head")
    assert "Do not stamp an older database" in error.value.stderr
    assert path.read_bytes() == before
    _legacy_alembic(url, "head")
    before = path.read_bytes()
    _alembic(url, "head")
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT email,password_hash FROM users WHERE id='retained'").fetchone() == (
            "owner@example.test", "encrypted-placeholder")


def _alembic(database_url: str, revision: str, command: str = "upgrade", *, legacy=False, allow_drop=False) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-c",
         "import sys; from argparse import Namespace; from alembic.config import Config; from alembic import command; "
         "config=Config(\"alembic.ini\"); "
         "config.set_main_option(\"script_location\",sys.argv[1]); "
         "config.cmd_opts=Namespace(x=[\"allow_baseline_drop=true\"] if sys.argv[4]==\"true\" else []); "
         "getattr(command,sys.argv[2])(config,sys.argv[3])",
         str(LEGACY_SCRIPT if legacy else API_ROOT / "alembic"), command, revision, str(allow_drop).lower()],
        cwd=API_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _legacy_alembic(database_url, revision, command="upgrade"):
    _alembic(database_url, revision, command, legacy=True)
    if command == "upgrade" and revision == "head":
        # Fully transformed historical data must also open with the new baseline.
        _alembic(database_url, "head")


def test_populated_0005_portfolio_is_backfilled_without_inventing_history(tmp_path: Path) -> None:
    database_path = tmp_path / "populated-0005.sqlite"
    database_url = f"sqlite:///{database_path}"
    _legacy_alembic(database_url, "0005_live_data")

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            INSERT INTO exchanges(id, code, name, timezone)
            VALUES('ex1', 'PSX', 'Pakistan Stock Exchange', 'Asia/Karachi');
            INSERT INTO users(id, email, password_hash, is_active, created_at, updated_at)
            VALUES('u1', 'legacy@example.com', 'x', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            INSERT INTO companies(id, symbol, name, sector, exchange_id, is_active, created_at, updated_at)
            VALUES('c1', 'MEBL', 'Meezan Bank', 'Commercial Banks', 'ex1', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            INSERT INTO portfolios(id, user_id, name, base_currency, created_at, updated_at, source_mode, provider_name)
            VALUES('p1', 'u1', 'Legacy', 'PKR', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'manual', 'ManualPortfolioProvider');
            INSERT INTO portfolio_holdings(id, portfolio_id, company_id, symbol, quantity, average_cost, created_at, updated_at)
            VALUES('h1', 'p1', 'c1', 'MEBL', 10, 100, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            INSERT INTO portfolio_transactions(id, portfolio_id, company_id, symbol, transaction_type, quantity, price, amount, transaction_date, source, created_at)
            VALUES('t1', 'p1', 'c1', 'MEBL', 'buy', 2, 90, 180, '2025-01-01', 'manual', CURRENT_TIMESTAMP);
            """
        )

    _legacy_alembic(database_url, "head")

    with sqlite3.connect(database_path) as connection:
        instrument = connection.execute(
            "SELECT id, company_id FROM instruments WHERE symbol='MEBL'"
        ).fetchone()
        holding_instrument = connection.execute(
            "SELECT instrument_id FROM portfolio_holdings WHERE id='h1'"
        ).fetchone()
        transaction_instrument = connection.execute(
            "SELECT instrument_id FROM portfolio_transactions WHERE id='t1'"
        ).fetchone()
        portfolio_history = connection.execute(
            "SELECT history_start, history_complete FROM portfolios WHERE id='p1'"
        ).fetchone()
        baseline = connection.execute(
            "SELECT quantity, average_cost FROM portfolio_position_snapshots WHERE portfolio_id='p1'"
        ).fetchone()

    assert instrument is not None and instrument[1] == "c1"
    assert holding_instrument == (instrument[0],)
    assert transaction_instrument == (instrument[0],)
    assert portfolio_history[0] is not None and portfolio_history[1] == 0
    assert baseline == (10, 100)


def test_global_evidence_migration_round_trip(tmp_path: Path) -> None:
    database_path = tmp_path / "global-evidence.sqlite"
    database_url = f"sqlite:///{database_path}"
    _legacy_alembic(database_url, "0014_phase2_ingestion_plane")
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            INSERT INTO events(id, event_type, title, occurred_at, details_json)
            VALUES('legacy-event', 'news', 'Legacy event', CURRENT_TIMESTAMP, '{}');
            INSERT INTO event_sources(id, event_id, source_url, source_name)
            VALUES('legacy-source', 'legacy-event', 'https://example.com/legacy', 'Legacy');
            """
        )
    _legacy_alembic(database_url, "head")

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        event_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('events')")
        }
        source_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('event_sources')")
        }
        candidate_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list('discovery_candidates')")
        }
        legacy_event = connection.execute(
            "SELECT cluster_status, cluster_version, updated_at FROM events "
            "WHERE id='legacy-event'"
        ).fetchone()
        legacy_source = connection.execute(
            "SELECT selection_status, selection_reasons_json FROM event_sources "
            "WHERE id='legacy-source'"
        ).fetchone()

    assert {
        "evidence_source_configs",
        "evidence_source_states",
        "discovery_candidates",
    }.issubset(tables)
    assert {"cluster_key", "topic", "geography", "cluster_status", "updated_at"}.issubset(
        event_columns
    )
    assert {"candidate_id", "evidence_role", "selection_status"}.issubset(source_columns)
    assert "ix_discovery_candidate_status_attempt" in candidate_indexes
    assert "ix_discovery_candidate_source_published" in candidate_indexes
    assert legacy_event is not None
    assert legacy_event[:2] == ("active", "deterministic-v1")
    assert legacy_event[2] is not None
    assert legacy_source == ("legacy", "[]")

    _legacy_alembic(database_url, "0014_phase2_ingestion_plane", command="downgrade")
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        event_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('events')")
        }
    assert "discovery_candidates" not in tables
    assert "cluster_key" not in event_columns

    _legacy_alembic(database_url, "head")


def test_stored_evidence_events_are_classified_from_retained_sources(tmp_path: Path) -> None:
    database_path = tmp_path / "stored-evidence-classification.sqlite"
    database_url = f"sqlite:///{database_path}"
    _legacy_alembic(database_url, "0021_ingestion_audit_repairs")

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            INSERT INTO events(id, event_type, title, occurred_at, details_json)
            VALUES
              ('psx-event', 'evidence_story', 'PSX notice', CURRENT_TIMESTAMP, '{}'),
              ('publisher-event', 'evidence_story', 'Publisher story', CURRENT_TIMESTAMP, '{}'),
              ('unsourced-event', 'evidence_story', 'No retained source', CURRENT_TIMESTAMP, '{}');
            INSERT INTO event_sources(id, event_id, source_url, source_name)
            VALUES
              ('psx-source', 'psx-event', 'https://dps.psx.com.pk/notice/1', 'Pakistan Stock Exchange'),
              ('publisher-source', 'publisher-event', 'https://example.test/story/1', 'Observed Publisher');
            """
        )

    _legacy_alembic(database_url, "head")

    with sqlite3.connect(database_path) as connection:
        classifications = dict(
            connection.execute("SELECT id, event_type FROM events").fetchall()
        )

    assert classifications == {
        "psx-event": "announcement",
        "publisher-event": "news",
        "unsourced-event": "evidence_story",
    }


def test_phase6_normalized_event_tables_are_additive(tmp_path: Path) -> None:
    database_path = tmp_path / "phase6-events.sqlite"
    database_url = f"sqlite:///{database_path}"
    _legacy_alembic(database_url, "head")

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        normalized_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('normalized_events')")
        }

    assert {"events", "normalized_events", "normalized_event_evidence", "normalized_event_subjects"}.issubset(tables)
    assert {
        "event_type", "classification_status", "factor", "materiality", "confidence",
        "freshness_score", "freshness_status", "detection_version",
    }.issubset(normalized_columns)
