"""Append-only corrections preserve original entries and their audit history."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade():
    op.create_table(
        "ledger_corrections",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column(
            "original_id",
            sa.BigInteger(),
            sa.ForeignKey("ledger_entries.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "replacement_id", sa.BigInteger(), sa.ForeignKey("ledger_entries.id"), unique=True
        ),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("owners.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        sa.Column("request_body", sa.Text(), nullable=False),
        sa.UniqueConstraint("account_id", "request_key"),
    )
    # Active-history uniqueness is checked under the account lock during replay.
    op.drop_index("one_opening_cash", table_name="ledger_entries")
    op.drop_index("one_opening_position", table_name="ledger_entries")


def downgrade():
    # Restoring old constraints would revive superseded financial records.
    raise RuntimeError("Restore a pre-correction database backup to downgrade safely")
