"""phase 2 market data

Revision ID: 0002_phase_2
Revises: 0001_phase_1
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase_2"
down_revision: str | None = "0001_phase_1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exchanges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_exchanges_code"), "exchanges", ["code"], unique=True)

    op.create_table(
        "companies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("exchange_id", sa.String(length=36), nullable=False),
        sa.Column("official_website", sa.String(length=500), nullable=True),
        sa.Column("psx_url", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["exchange_id"], ["exchanges.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_companies_sector"), "companies", ["sector"], unique=False)
    op.create_index(op.f("ix_companies_symbol"), "companies", ["symbol"], unique=True)

    op.create_table(
        "market_prices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("high", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("low", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("previous_close", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("change", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("change_percent", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("value", sa.Numeric(precision=24, scale=4), nullable=False),
        sa.Column("market_cap", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "trade_date", "source", name="uq_market_prices_symbol_date_source"),
    )
    op.create_index(op.f("ix_market_prices_company_id"), "market_prices", ["company_id"], unique=False)
    op.create_index(op.f("ix_market_prices_symbol"), "market_prices", ["symbol"], unique=False)
    op.create_index(op.f("ix_market_prices_trade_date"), "market_prices", ["trade_date"], unique=False)

    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("index_name", sa.String(length=120), nullable=False),
        sa.Column("index_value", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("index_change", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("index_change_percent", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("total_volume", sa.Integer(), nullable=False),
        sa.Column("total_value", sa.Numeric(precision=24, scale=4), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_date", "index_name", "source", name="uq_market_snapshot_date_index"),
    )
    op.create_index(
        op.f("ix_market_snapshots_snapshot_date"),
        "market_snapshots",
        ["snapshot_date"],
        unique=False,
    )

    op.create_table(
        "sector_daily_stats",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("total_volume", sa.Integer(), nullable=False),
        sa.Column("total_value", sa.Numeric(precision=24, scale=4), nullable=False),
        sa.Column("average_change_percent", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("advancers", sa.Integer(), nullable=False),
        sa.Column("decliners", sa.Integer(), nullable=False),
        sa.Column("unchanged", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sector", "trade_date", "source", name="uq_sector_stats_sector_date_source"),
    )
    op.create_index(op.f("ix_sector_daily_stats_sector"), "sector_daily_stats", ["sector"], unique=False)
    op.create_index(
        op.f("ix_sector_daily_stats_trade_date"),
        "sector_daily_stats",
        ["trade_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sector_daily_stats_trade_date"), table_name="sector_daily_stats")
    op.drop_index(op.f("ix_sector_daily_stats_sector"), table_name="sector_daily_stats")
    op.drop_table("sector_daily_stats")
    op.drop_index(op.f("ix_market_snapshots_snapshot_date"), table_name="market_snapshots")
    op.drop_table("market_snapshots")
    op.drop_index(op.f("ix_market_prices_trade_date"), table_name="market_prices")
    op.drop_index(op.f("ix_market_prices_symbol"), table_name="market_prices")
    op.drop_index(op.f("ix_market_prices_company_id"), table_name="market_prices")
    op.drop_table("market_prices")
    op.drop_index(op.f("ix_companies_symbol"), table_name="companies")
    op.drop_index(op.f("ix_companies_sector"), table_name="companies")
    op.drop_table("companies")
    op.drop_index(op.f("ix_exchanges_code"), table_name="exchanges")
    op.drop_table("exchanges")
