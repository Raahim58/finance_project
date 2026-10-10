import json

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.ingestion.evidence import Candidate
from app.models.workstation import DataSource
from app.services.evidence_canary_service import reserve_fetch
from app.services.evidence_pipeline import ensure_source_config, persist_candidate


@pytest.mark.usefixtures("database")
def test_breadth_source_config_persists_shared_canary_and_provenance():
    with SessionLocal() as db:
        data_source, config, _ = ensure_source_config(db, "semiconductor_engineering")
        db.commit()

        assert data_source.enabled is settings.evidence_pass4_breadth_enabled
        assert config.canary_group == "pass4_breadth"
        assert config.daily_fetch_budget == 6
        assert config.daily_selected_budget == 3
        assert json.loads(config.provenance_json)["adapter"] == "rss"
        assert json.loads(config.provenance_json)["authority"] == "specialist"
        assert json.loads(config.fallback_json)["browser"] is False
        assert db.scalar(select(DataSource).where(DataSource.id == data_source.id)) is not None


@pytest.mark.usefixtures("database")
def test_official_and_breadth_sources_share_one_global_fetch_ceiling(monkeypatch):
    from datetime import UTC, datetime

    monkeypatch.setattr(settings, "evidence_canary_fetch_daily", 1)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        official_config = ensure_source_config(db, "secp_releases")[1]
        breadth_config = ensure_source_config(db, "semiconductor_engineering")[1]
        official, _ = persist_candidate(
            db,
            official_config,
            Candidate(
                "secp_releases",
                "https://www.secp.gov.pk/media-center/shared-budget",
                "Pakistan securities policy update",
                "SECP",
                now,
                "listing_page",
                external_id="shared-budget-official",
            ),
        )
        breadth, _ = persist_candidate(
            db,
            breadth_config,
            Candidate(
                "semiconductor_engineering",
                "https://semiengineering.com/shared-budget",
                "Semiconductor supply update",
                "Semiconductor Engineering",
                now,
                "rss_atom",
                external_id="shared-budget-breadth",
            ),
        )

        assert reserve_fetch(db, official, official_config, now=now).allowed
        assert not reserve_fetch(db, breadth, breadth_config, now=now).allowed
