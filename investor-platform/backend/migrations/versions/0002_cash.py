"""Auditable, idempotent cash entries."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("note", sa.String(240), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("owners.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        sa.Column("request_body", sa.Text(), nullable=False),
        sa.UniqueConstraint("account_id", "request_key", name="ledger_request_key"),
        sa.CheckConstraint("kind IN ('opening_cash','deposit','withdrawal')", name="ledger_kind"),
        sa.CheckConstraint(
            "amount >= 0 AND (kind = 'opening_cash' OR amount > 0)", name="ledger_amount"
        ),
    )
    op.create_index("ledger_order", "ledger_entries", ["account_id", "effective_date", "id"])
    op.create_index(
        "one_opening_cash",
        "ledger_entries",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'opening_cash'"),
    )


def downgrade():
    op.drop_table("ledger_entries")
