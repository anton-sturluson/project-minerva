"""Opening positions and atomic equity trades."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    op.create_table(
        "securities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("exchange", sa.String(12), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "ticker", "exchange", "currency", name="security_identity"
        ),
    )
    op.alter_column("ledger_entries", "amount", type_=sa.Numeric(48, 16))
    op.add_column(
        "ledger_entries", sa.Column("security_id", sa.Uuid(), sa.ForeignKey("securities.id"))
    )
    op.add_column("ledger_entries", sa.Column("quantity", sa.Numeric(20, 8)))
    op.add_column("ledger_entries", sa.Column("price", sa.Numeric(20, 8)))
    op.add_column(
        "ledger_entries", sa.Column("fees", sa.Numeric(24, 8), nullable=False, server_default="0")
    )
    op.add_column("ledger_entries", sa.Column("cost_basis", sa.Numeric(24, 8)))
    op.drop_constraint("ledger_kind", "ledger_entries")
    op.drop_constraint("ledger_amount", "ledger_entries")
    op.create_check_constraint(
        "ledger_kind",
        "ledger_entries",
        "kind IN ('opening_cash','deposit','withdrawal','opening_position','buy','sell')",
    )
    op.create_check_constraint(
        "ledger_amount",
        "ledger_entries",
        "amount >= 0 AND (kind IN ('opening_cash','opening_position','sell') OR amount > 0)",
    )
    op.create_check_constraint(
        "entry_shape",
        "ledger_entries",
        """
      (kind IN ('opening_cash','deposit','withdrawal') AND security_id IS NULL
        AND quantity IS NULL AND price IS NULL AND fees = 0 AND cost_basis IS NULL)
      OR (kind = 'opening_position' AND security_id IS NOT NULL AND quantity > 0
        AND quantity IS NOT NULL AND price IS NULL AND fees = 0 AND amount = 0
        AND (cost_basis IS NULL OR cost_basis >= 0))
      OR (kind IN ('buy','sell') AND security_id IS NOT NULL AND quantity IS NOT NULL
        AND quantity > 0 AND price IS NOT NULL AND price > 0 AND fees >= 0 AND cost_basis IS NULL)
    """,
    )
    op.create_index(
        "one_opening_position",
        "ledger_entries",
        ["account_id", "security_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'opening_position'"),
    )


def downgrade():
    # Cash migration cannot represent investments; refuse destructive rollback.
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM ledger_entries WHERE security_id IS NOT NULL")
    ):
        raise RuntimeError("Trade records exist; restore a backup instead of dropping them")
    op.drop_index("one_opening_position", table_name="ledger_entries")
    op.drop_constraint("entry_shape", "ledger_entries")
    op.drop_constraint("ledger_kind", "ledger_entries")
    op.drop_constraint("ledger_amount", "ledger_entries")
    op.create_check_constraint(
        "ledger_kind", "ledger_entries", "kind IN ('opening_cash','deposit','withdrawal')"
    )
    op.create_check_constraint(
        "ledger_amount", "ledger_entries", "amount >= 0 AND (kind = 'opening_cash' OR amount > 0)"
    )
    for name in ["security_id", "quantity", "price", "fees", "cost_basis"]:
        op.drop_column("ledger_entries", name)
    op.alter_column("ledger_entries", "amount", type_=sa.Numeric(24, 8))
    op.drop_table("securities")
