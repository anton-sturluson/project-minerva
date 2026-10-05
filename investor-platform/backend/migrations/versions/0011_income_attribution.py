"""Attribute dividends and separate economic recognition from cash payment."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"


def upgrade():
    op.add_column("ledger_entries", sa.Column("income_kind", sa.String(16)))
    op.add_column("ledger_entries", sa.Column("income_security_id", postgresql.UUID()))
    op.add_column("ledger_entries", sa.Column("accrual_date", sa.Date()))
    op.create_foreign_key(
        "income_security_fk", "ledger_entries", "securities", ["income_security_id"], ["id"]
    )
    op.create_check_constraint(
        "income_attribution",
        "ledger_entries",
        """
        (income_kind IS NULL AND income_security_id IS NULL AND accrual_date IS NULL)
        OR (kind = 'income' AND income_kind IS NOT NULL AND income_kind IN ('interest','other')
            AND income_security_id IS NULL AND accrual_date IS NULL)
        OR (kind = 'income' AND income_kind IS NOT NULL AND income_kind = 'dividend'
                AND income_security_id IS NOT NULL
            AND accrual_date IS NOT NULL AND accrual_date <= effective_date)
    """,
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM ledger_entries WHERE income_kind IS NOT NULL)")
    ):
        raise RuntimeError("Attributed income exists; restore a backup instead of discarding it")
    op.drop_constraint("income_attribution", "ledger_entries", type_="check")
    op.drop_constraint("income_security_fk", "ledger_entries", type_="foreignkey")
    for name in ("accrual_date", "income_security_id", "income_kind"):
        op.drop_column("ledger_entries", name)
