"""domain data and portfolio foundations

Revision ID: 0006_domain_data
Revises: 0005_live_data
"""
from collections.abc import Sequence
from uuid import uuid4
import sqlalchemy as sa
from alembic import op

revision: str = "0006_domain_data"
down_revision: str | None = "0005_live_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("portfolios", sa.Column("description", sa.Text()))
    op.add_column("portfolios", sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("portfolios", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column("portfolios", sa.Column("history_start", sa.Date()))
    op.add_column("portfolios", sa.Column("history_complete", sa.Boolean(), nullable=False, server_default=sa.false()))
    for name, column in [
        ("currency", sa.Column("currency", sa.String(10), nullable=False, server_default="PKR")),
        ("fees", sa.Column("fees", sa.Numeric(18, 4), nullable=False, server_default="0")),
        ("taxes", sa.Column("taxes", sa.Numeric(18, 4), nullable=False, server_default="0")),
        ("settlement_date", sa.Column("settlement_date", sa.Date())),
        ("external_id", sa.Column("external_id", sa.String(120))),
        # SQLite cannot add a foreign-key constraint with ALTER TABLE. Ownership-safe
        # services validate this self-reference; PostgreSQL can receive the FK in a
        # later constraint-only migration without blocking local/test upgrades.
        ("reversal_of_id", sa.Column("reversal_of_id", sa.String(36))),
    ]:
        op.add_column("portfolio_transactions", column)
    op.create_table("instruments",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id"), unique=True),
        sa.Column("symbol", sa.String(30), nullable=False, unique=True), sa.Column("name", sa.String(255), nullable=False),
        sa.Column("instrument_type", sa.String(40), nullable=False), sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("country", sa.String(2), nullable=False), sa.Column("sector", sa.String(120)), sa.Column("active_from", sa.Date()),
        sa.Column("active_to", sa.Date()), sa.Column("metadata_json", sa.Text(), nullable=False))
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"], unique=True)
    connection = op.get_bind()
    companies = connection.execute(sa.text("SELECT id, symbol, name, sector FROM companies")).mappings()
    for company in companies:
        connection.execute(
            sa.text(
                "INSERT INTO instruments (id, company_id, symbol, name, instrument_type, currency, country, sector, metadata_json) "
                "VALUES (:id, :company_id, :symbol, :name, 'equity', 'PKR', 'PK', :sector, '{}')"
            ),
            {"id": str(uuid4()), "company_id": company["id"], "symbol": company["symbol"], "name": company["name"], "sector": company["sector"]},
        )
    # Existing mutable holdings establish an honest migration baseline. This does
    # not invent cash or pre-baseline performance.
    connection.execute(sa.text("UPDATE portfolios SET history_start = CURRENT_DATE, history_complete = 0 WHERE EXISTS (SELECT 1 FROM portfolio_holdings h WHERE h.portfolio_id = portfolios.id)"))
    op.create_table("data_sources",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("source_type", sa.String(40), nullable=False), sa.Column("base_url", sa.String(500)), sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("freshness_sla_minutes", sa.Integer()), sa.Column("enabled", sa.Boolean(), nullable=False), sa.Column("use_notes", sa.Text()))
    op.create_table("source_artifacts",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("data_source_id", sa.String(36), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False), sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True)), sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("content_type", sa.String(120)), sa.Column("storage_path", sa.String(1000)), sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("response_metadata_json", sa.Text(), nullable=False))
    op.create_table("investor_financial_profile_versions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("profile_json", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("portfolio_ips_versions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("constraints_json", sa.Text(), nullable=False),
        sa.Column("required_return", sa.Numeric(12, 8)), sa.Column("confirmed_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("allocation_sets",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("allocation_items",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("allocation_set_id", sa.String(36), sa.ForeignKey("allocation_sets.id"), nullable=False),
        sa.Column("symbol", sa.String(30), nullable=False), sa.Column("target_weight", sa.Numeric(12, 8), nullable=False), sa.Column("locked", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("allocation_set_id", "symbol", name="uq_allocation_symbol"))


def downgrade() -> None:
    for table in ["allocation_items", "allocation_sets", "portfolio_ips_versions", "investor_financial_profile_versions", "source_artifacts", "data_sources", "instruments"]:
        op.drop_table(table)
    for name in ["reversal_of_id", "external_id", "settlement_date", "taxes", "fees", "currency"]:
        op.drop_column("portfolio_transactions", name)
    for name in ["history_complete", "history_start", "archived_at", "is_default", "description"]:
        op.drop_column("portfolios", name)
