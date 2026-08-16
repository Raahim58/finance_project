"""fix Pakistan fiscal macro series contract

Revision ID: 0020_fix_macro_fiscal_series
Revises: 0019_macro_provider_ladder
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0020_fix_macro_fiscal_series"
down_revision: str | None = "0019_macro_provider_ladder"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Preserve the existing canonical series row/id so any observations,
    # foreign keys and provider relationships remain attached.
    op.execute(
        """
        UPDATE macro_series
        SET
            key = 'PK_NET_LENDING_GDP',
            name = 'Pakistan general-government net lending/borrowing'
        WHERE key = 'PK_CASH_BALANCE_GDP'
        """
    )

    # Correct the World Bank fallback contract.
    op.execute(
        """
        UPDATE macro_series_providers
        SET
            provider_key = 'world_bank:PAK:GC.NLD.TOTL.GD.ZS',
            source_series_id = 'GC.NLD.TOTL.GD.ZS'
        WHERE provider_key = 'world_bank:PAK:GC.BAL.CASH.GD.ZS'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE macro_series_providers
        SET
            provider_key = 'world_bank:PAK:GC.BAL.CASH.GD.ZS',
            source_series_id = 'GC.BAL.CASH.GD.ZS'
        WHERE provider_key = 'world_bank:PAK:GC.NLD.TOTL.GD.ZS'
        """
    )

    op.execute(
        """
        UPDATE macro_series
        SET
            key = 'PK_CASH_BALANCE_GDP',
            name = 'Pakistan government cash balance'
        WHERE key = 'PK_NET_LENDING_GDP'
        """
    )