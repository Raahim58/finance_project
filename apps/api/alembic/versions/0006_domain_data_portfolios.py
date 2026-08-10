"""domain data, provenance, ledger, profile, IPS, and allocations

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
    for column in [
        sa.Column("description", sa.Text()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("history_start", sa.Date()),
        sa.Column("history_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("goal_summary", sa.Text()),
        sa.Column("benchmark_instrument_id", sa.String(36)),
    ]:
        op.add_column("portfolios", column)

    for column in [
        sa.Column("currency", sa.String(10), nullable=False, server_default="PKR"),
        sa.Column("fees", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("taxes", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("settlement_date", sa.Date()),
        sa.Column("external_id", sa.String(120)),
        sa.Column("reversal_of_id", sa.String(36)),
        sa.Column("instrument_id", sa.String(36)),
    ]:
        op.add_column("portfolio_transactions", column)
    op.add_column("portfolio_holdings", sa.Column("instrument_id", sa.String(36)))

    op.create_table(
        "instruments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id"), unique=True),
        sa.Column("symbol", sa.String(30), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("instrument_type", sa.String(40), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("sector", sa.String(120)),
        sa.Column("active_from", sa.Date()),
        sa.Column("active_to", sa.Date()),
        sa.Column("metadata_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"], unique=True)
    op.create_table(
        "instrument_aliases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instrument_id", sa.String(36), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("alias", sa.String(120), nullable=False),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_to", sa.Date()),
        sa.UniqueConstraint("provider", "alias", "valid_from", name="uq_instrument_alias_validity"),
    )

    connection = op.get_bind()
    for company in connection.execute(sa.text("SELECT id, symbol, name, sector FROM companies")).mappings():
        instrument_id = str(uuid4())
        connection.execute(
            sa.text("INSERT INTO instruments (id, company_id, symbol, name, instrument_type, currency, country, sector, metadata_json) VALUES (:id, :company_id, :symbol, :name, 'equity', 'PKR', 'PK', :sector, '{}')"),
            {**company, "id": instrument_id, "company_id": company["id"]},
        )
        connection.execute(sa.text("UPDATE portfolio_holdings SET instrument_id=:instrument_id WHERE company_id=:company_id"), {"instrument_id": instrument_id, "company_id": company["id"]})
        connection.execute(sa.text("UPDATE portfolio_transactions SET instrument_id=:instrument_id WHERE company_id=:company_id"), {"instrument_id": instrument_id, "company_id": company["id"]})

    op.create_table(
        "data_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("base_url", sa.String(500)),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("freshness_sla_minutes", sa.Integer()),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("use_notes", sa.Text()),
    )
    op.create_table(
        "source_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("data_source_id", sa.String(36), sa.ForeignKey("data_sources.id"), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("http_method", sa.String(10), nullable=False),
        sa.Column("request_fingerprint", sa.String(64)),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_at", sa.DateTime(timezone=True)),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("content_type", sa.String(120)),
        sa.Column("storage_path", sa.String(1000)),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("response_metadata_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_key", sa.String(120), nullable=False),
        sa.Column("run_key", sa.String(160), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("parent_run_id", sa.String(36), sa.ForeignKey("ingestion_runs.id")),
        sa.Column("attempted_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_class", sa.String(160)),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("job_key", "run_key", name="uq_ingestion_job_run"),
    )
    op.create_table(
        "market_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instrument_id", sa.String(36), sa.ForeignKey("instruments.id")),
        sa.Column("series_key", sa.String(160)),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False),
        sa.Column("values_json", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(10)),
        sa.Column("unit", sa.String(40)),
        sa.Column("adjustment_state", sa.String(40), nullable=False),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("source_artifacts.id"), nullable=False),
        sa.Column("is_selected", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("instrument_id", "effective_at", "frequency", "artifact_id", name="uq_market_observation_source"),
    )
    op.create_table(
        "data_quality_issues",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("source_artifacts.id")),
        sa.Column("observation_id", sa.String(36)),
        sa.Column("rule", sa.String(120), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text()),
        sa.Column("selection_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "investor_financial_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("current_version_id", sa.String(36)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "investor_financial_profile_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("profile_json", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "version", name="uq_profile_version"),
    )
    op.create_table(
        "portfolio_ips_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("constraints_json", sa.Text(), nullable=False),
        sa.Column("required_return", sa.Numeric(12, 8)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("portfolio_id", "version", name="uq_ips_version"),
    )
    op.create_table(
        "portfolio_ips",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False, unique=True),
        sa.Column("current_version_id", sa.String(36), sa.ForeignKey("portfolio_ips_versions.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("portfolios", sa.Column("selected_ips_version_id", sa.String(36)))

    op.create_table(
        "portfolio_cash_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("portfolio_id", "currency", "name", name="uq_portfolio_cash_account"),
    )
    op.create_table(
        "portfolio_position_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("instrument_id", sa.String(36), sa.ForeignKey("instruments.id"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 6), nullable=False),
        sa.Column("average_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("source_transaction_id", sa.String(36), sa.ForeignKey("portfolio_transactions.id")),
        sa.UniqueConstraint("portfolio_id", "instrument_id", "snapshot_date", name="uq_position_snapshot"),
    )
    op.create_table(
        "portfolio_cash_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cash_account_id", sa.String(36), sa.ForeignKey("portfolio_cash_accounts.id"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("balance", sa.Numeric(24, 4), nullable=False),
        sa.Column("source_transaction_id", sa.String(36), sa.ForeignKey("portfolio_transactions.id")),
        sa.UniqueConstraint("cash_account_id", "snapshot_date", name="uq_cash_snapshot"),
    )
    op.create_table(
        "allocation_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("base_value", sa.Numeric(24, 4)),
        sa.Column("created_by_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "allocation_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("allocation_set_id", sa.String(36), sa.ForeignKey("allocation_sets.id"), nullable=False),
        sa.Column("symbol", sa.String(30), nullable=False),
        sa.Column("instrument_id", sa.String(36), sa.ForeignKey("instruments.id")),
        sa.Column("is_cash", sa.Boolean(), nullable=False),
        sa.Column("target_weight", sa.Numeric(12, 8), nullable=False),
        sa.Column("target_amount", sa.Numeric(24, 4)),
        sa.Column("target_quantity", sa.Numeric(24, 6)),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("allocation_set_id", "symbol", name="uq_allocation_symbol"),
    )

    connection.execute(
        sa.text(
            "UPDATE portfolios SET history_start=CURRENT_DATE, history_complete=:history_complete "
            "WHERE EXISTS (SELECT 1 FROM portfolio_holdings h WHERE h.portfolio_id=portfolios.id)"
        ),
        {"history_complete": False},
    )
    for holding in connection.execute(sa.text("SELECT portfolio_id, instrument_id, quantity, average_cost FROM portfolio_holdings WHERE instrument_id IS NOT NULL")).mappings():
        connection.execute(
            sa.text("INSERT INTO portfolio_position_snapshots (id, portfolio_id, instrument_id, snapshot_date, quantity, average_cost, source_transaction_id) VALUES (:id, :portfolio_id, :instrument_id, CURRENT_DATE, :quantity, :average_cost, NULL)"),
            {"id": str(uuid4()), **holding},
        )


def downgrade() -> None:
    for table in [
        "allocation_items", "allocation_sets", "portfolio_cash_snapshots",
        "portfolio_position_snapshots", "portfolio_cash_accounts", "portfolio_ips",
    ]:
        op.drop_table(table)
    op.drop_column("portfolios", "selected_ips_version_id")
    for table in [
        "portfolio_ips_versions", "investor_financial_profile_versions",
        "investor_financial_profiles", "data_quality_issues", "market_observations",
        "ingestion_runs", "source_artifacts", "data_sources", "instrument_aliases",
    ]:
        op.drop_table(table)
    op.drop_index("ix_instruments_symbol", table_name="instruments")
    op.drop_table("instruments")
    op.drop_column("portfolio_holdings", "instrument_id")
    for name in ["instrument_id", "reversal_of_id", "external_id", "settlement_date", "taxes", "fees", "currency"]:
        op.drop_column("portfolio_transactions", name)
    for name in ["benchmark_instrument_id", "goal_summary", "history_complete", "history_start", "archived_at", "is_default", "description"]:
        op.drop_column("portfolios", name)
