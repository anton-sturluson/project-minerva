"""Persist provider histories and explicit historical listing identity."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"


def upgrade():
    op.add_column("securities", sa.Column("market_identity", postgresql.JSONB(), nullable=True))
    op.create_table(
        "market_cache",
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), primary_key=True),
        sa.Column("provider", sa.String(20), primary_key=True),
        sa.Column("symbol", sa.String(40), primary_key=True),
        sa.Column("start", sa.Date(), nullable=False),
        sa.Column("end", sa.Date(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("market_cache")
    op.drop_column("securities", "market_identity")
