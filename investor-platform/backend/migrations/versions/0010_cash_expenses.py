"""Cash expenses reduce investment return; withdrawals are external flows."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"

SHAPE = """
(kind IN ('opening_cash','deposit','withdrawal','income'{expense}) AND security_id IS NULL
 AND quantity IS NULL AND price IS NULL AND fees = 0 AND cost_basis IS NULL)
OR (kind IN ('opening_position','transfer_in') AND security_id IS NOT NULL AND quantity > 0
 AND quantity IS NOT NULL AND price IS NULL AND fees = 0 AND amount = 0
 AND (cost_basis IS NULL OR cost_basis >= 0))
OR (kind IN ('buy','sell') AND security_id IS NOT NULL AND quantity IS NOT NULL
 AND quantity > 0 AND price IS NOT NULL AND price > 0 AND fees >= 0 AND cost_basis IS NULL)
"""


def constraints(expense):
    for name in ("ledger_kind", "entry_shape"):
        op.drop_constraint(name, "ledger_entries", type_="check")
    op.create_check_constraint(
        "ledger_kind",
        "ledger_entries",
        "kind IN ('opening_cash','deposit','withdrawal','income',"
        "'opening_position','transfer_in','buy','sell'" + expense + ")",
    )
    op.create_check_constraint("entry_shape", "ledger_entries", SHAPE.format(expense=expense))


def upgrade():
    constraints(",'expense'")


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM ledger_entries WHERE kind='expense')")
    ):
        raise RuntimeError("Expenses exist; restore a backup instead of downgrading")
    constraints("")
