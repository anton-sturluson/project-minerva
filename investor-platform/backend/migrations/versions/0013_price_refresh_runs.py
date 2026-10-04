"""Persist daily price collection status across application restarts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"


def upgrade():
    op.create_table(
        "price_refresh_runs",
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), primary_key=True),
        sa.Column("scheduled_date", sa.Date(), primary_key=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=False),
    )


def downgrade():
    op.drop_table("price_refresh_runs")
