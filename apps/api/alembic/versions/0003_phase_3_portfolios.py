"""phase 3 portfolios

Revision ID: 0003_phase_3
Revises: 0002_phase_2
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase_3"
down_revision: str | None = "0002_phase_2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("base_currency", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_portfolios_user_id"), "portfolios", ["user_id"], unique=False)

    op.create_table(
        "portfolio_holdings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("portfolio_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=24, scale=6), nullable=False),
        sa.Column("average_cost", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("portfolio_id", "symbol", name="uq_portfolio_holding_symbol"),
    )
    op.create_index(
        op.f("ix_portfolio_holdings_company_id"),
        "portfolio_holdings",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_portfolio_holdings_portfolio_id"),
        "portfolio_holdings",
        ["portfolio_id"],
        unique=False,
    )
    op.create_index(op.f("ix_portfolio_holdings_symbol"), "portfolio_holdings", ["symbol"], unique=False)

    op.create_table(
        "portfolio_transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("portfolio_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=True),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("transaction_type", sa.String(length=40), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("price", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("amount", sa.Numeric(precision=24, scale=4), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_portfolio_transactions_company_id"),
        "portfolio_transactions",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_portfolio_transactions_portfolio_id"),
        "portfolio_transactions",
        ["portfolio_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_portfolio_transactions_symbol"),
        "portfolio_transactions",
        ["symbol"],
        unique=False,
    )
    op.create_index(
        op.f("ix_portfolio_transactions_transaction_date"),
        "portfolio_transactions",
        ["transaction_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_portfolio_transactions_transaction_date"), table_name="portfolio_transactions")
    op.drop_index(op.f("ix_portfolio_transactions_symbol"), table_name="portfolio_transactions")
    op.drop_index(op.f("ix_portfolio_transactions_portfolio_id"), table_name="portfolio_transactions")
    op.drop_index(op.f("ix_portfolio_transactions_company_id"), table_name="portfolio_transactions")
    op.drop_table("portfolio_transactions")
    op.drop_index(op.f("ix_portfolio_holdings_symbol"), table_name="portfolio_holdings")
    op.drop_index(op.f("ix_portfolio_holdings_portfolio_id"), table_name="portfolio_holdings")
    op.drop_index(op.f("ix_portfolio_holdings_company_id"), table_name="portfolio_holdings")
    op.drop_table("portfolio_holdings")
    op.drop_index(op.f("ix_portfolios_user_id"), table_name="portfolios")
    op.drop_table("portfolios")
