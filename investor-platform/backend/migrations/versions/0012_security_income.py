"""Link non-dividend income such as stock lending to the relevant security."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"

SHAPE = """
    (income_kind IS NULL AND income_security_id IS NULL AND accrual_date IS NULL)
    OR (kind = 'income' AND income_kind IS NOT NULL AND income_kind IN ('interest','other')
        {unattributed} AND accrual_date IS NULL)
    OR (kind = 'income' AND income_kind IS NOT NULL AND income_kind = 'dividend'
        AND income_security_id IS NOT NULL
        AND accrual_date IS NOT NULL AND accrual_date <= effective_date)
"""


def replace(unattributed):
    op.drop_constraint("income_attribution", "ledger_entries", type_="check")
    op.create_check_constraint(
        "income_attribution", "ledger_entries", SHAPE.format(unattributed=unattributed)
    )


def upgrade():
    replace("")


def downgrade():
    if op.get_bind().scalar(
        sa.text("""SELECT EXISTS (SELECT 1 FROM ledger_entries
        WHERE income_kind IN ('interest','other') AND income_security_id IS NOT NULL)""")
    ):
        raise RuntimeError(
            "Security-linked income exists; restore a backup instead of losing attribution"
        )
    replace("AND income_security_id IS NULL")
