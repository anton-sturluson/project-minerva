"""Dated in-kind share receipts without trade cash or invented acquisition basis."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"

OLD = {
    "ledger_kind": """kind IN ('opening_cash','deposit','withdrawal','income',
                              'opening_position','buy','sell')""",
    "ledger_amount": """amount >= 0 AND
        (kind IN ('opening_cash','opening_position','sell') OR amount > 0)""",
    "entry_shape": """
      (kind IN ('opening_cash','deposit','withdrawal','income') AND security_id IS NULL
        AND quantity IS NULL AND price IS NULL AND fees = 0 AND cost_basis IS NULL)
      OR (kind = 'opening_position' AND security_id IS NOT NULL AND quantity > 0
        AND quantity IS NOT NULL AND price IS NULL AND fees = 0 AND amount = 0
        AND (cost_basis IS NULL OR cost_basis >= 0))
      OR (kind IN ('buy','sell') AND security_id IS NOT NULL AND quantity IS NOT NULL
        AND quantity > 0 AND price IS NOT NULL AND price > 0 AND fees >= 0 AND cost_basis IS NULL)
    """,
}
NEW = {
    name: expression.replace("kind = 'opening_position'", "kind IN ('opening_position')").replace(
        "'opening_position'", "'opening_position','transfer_in'"
    )
    for name, expression in OLD.items()
}


def replace(definitions):
    for name, expression in definitions.items():
        op.drop_constraint(name, "ledger_entries", type_="check")
        op.create_check_constraint(name, "ledger_entries", expression)


def upgrade():
    replace(NEW)


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM ledger_entries WHERE kind='transfer_in')")
    ):
        raise RuntimeError("Share receipts exist; restore a backup instead of downgrading")
    replace(OLD)
