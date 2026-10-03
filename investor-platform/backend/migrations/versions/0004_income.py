"""Investment income is internal return, not an external deposit."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"

SHAPE = """
(kind IN ('opening_cash','deposit','withdrawal'{income}) AND security_id IS NULL
 AND quantity IS NULL AND price IS NULL AND fees = 0 AND cost_basis IS NULL)
OR (kind = 'opening_position' AND security_id IS NOT NULL AND quantity > 0
 AND quantity IS NOT NULL AND price IS NULL AND fees = 0 AND amount = 0
 AND (cost_basis IS NULL OR cost_basis >= 0))
OR (kind IN ('buy','sell') AND security_id IS NOT NULL AND quantity IS NOT NULL
 AND quantity > 0 AND price IS NOT NULL AND price > 0 AND fees >= 0 AND cost_basis IS NULL)
"""


def constraints(income):
    op.drop_constraint("ledger_kind", "ledger_entries")
    op.drop_constraint("entry_shape", "ledger_entries")
    op.create_check_constraint(
        "ledger_kind",
        "ledger_entries",
        "kind IN ('opening_cash','deposit','withdrawal','opening_position','buy','sell'"
        + income
        + ")",
    )
    op.create_check_constraint("entry_shape", "ledger_entries", SHAPE.format(income=income))


def upgrade():
    constraints(",'income'")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM ledger_entries WHERE kind = 'income'")):
        raise RuntimeError("Income records exist; restore a backup instead of removing support")
    constraints("")
