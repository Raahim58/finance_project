import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


API_ROOT = Path(__file__).resolve().parents[2]


def test_revision_identifiers_fit_default_alembic_version_column() -> None:
    config = Config()
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    revisions = ScriptDirectory.from_config(config).walk_revisions()
    assert all(len(revision.revision) <= 32 for revision in revisions)


def _alembic(database_url: str, revision: str, command: str = "upgrade") -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", command, revision],
        cwd=API_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_populated_0005_portfolio_is_backfilled_without_inventing_history(tmp_path: Path) -> None:
    database_path = tmp_path / "populated-0005.sqlite"
    database_url = f"sqlite:///{database_path}"
    _alembic(database_url, "0005_live_data")

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

    _alembic(database_url, "head")

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
    _alembic(database_url, "0014_phase2_ingestion_plane")
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            INSERT INTO events(id, event_type, title, occurred_at, details_json)
            VALUES('legacy-event', 'news', 'Legacy event', CURRENT_TIMESTAMP, '{}');
            INSERT INTO event_sources(id, event_id, source_url, source_name)
            VALUES('legacy-source', 'legacy-event', 'https://example.com/legacy', 'Legacy');
            """
        )
    _alembic(database_url, "head")

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

    _alembic(database_url, "0014_phase2_ingestion_plane", command="downgrade")
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

    _alembic(database_url, "head")
