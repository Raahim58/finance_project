"""classify already-ingested evidence events by their stored source

Revision ID: 0022_classify_stored_evidence
Revises: 0021_ingestion_audit_repairs
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0022_classify_stored_evidence"
down_revision: str | None = "0021_ingestion_audit_repairs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Official PSX candidates are company announcements. Use both the retained
    # source row and candidate configuration so historical rows remain
    # classifiable even if one side of the evidence relationship is absent.
    op.execute(
        """
        UPDATE events
        SET event_type = 'announcement'
        WHERE event_type = 'evidence_story'
          AND (
            EXISTS (
              SELECT 1 FROM event_sources
              WHERE event_sources.event_id = events.id
                AND event_sources.source_name = 'Pakistan Stock Exchange'
            )
            OR EXISTS (
              SELECT 1
              FROM discovery_candidates
              JOIN evidence_source_configs
                ON evidence_source_configs.id = discovery_candidates.source_config_id
              WHERE discovery_candidates.event_id = events.id
                AND evidence_source_configs.source_key = 'psx_announcements'
            )
          )
        """
    )
    # Every remaining generic evidence event with retained publisher provenance
    # is news/reporting evidence. Rows without any stored source stay generic.
    op.execute(
        """
        UPDATE events
        SET event_type = 'news'
        WHERE event_type = 'evidence_story'
          AND (
            EXISTS (
              SELECT 1 FROM event_sources
              WHERE event_sources.event_id = events.id
            )
            OR EXISTS (
              SELECT 1 FROM discovery_candidates
              WHERE discovery_candidates.event_id = events.id
            )
          )
        """
    )


def downgrade() -> None:
    # Only candidate-backed pipeline events are reverted. Legacy/native news
    # rows without a discovery candidate are left unchanged.
    op.execute(
        """
        UPDATE events
        SET event_type = 'evidence_story'
        WHERE event_type IN ('announcement', 'news')
          AND EXISTS (
            SELECT 1 FROM discovery_candidates
            WHERE discovery_candidates.event_id = events.id
          )
        """
    )
