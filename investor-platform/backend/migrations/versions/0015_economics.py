"""Add minimal economics facts and refresh state."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str = "0014"


def upgrade() -> None:
    """Add two small tables; source and series definitions remain in code."""
    op.create_table(
        "economic_observations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("series_key", sa.String(60), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(20, 6)),
        sa.Column("missing", sa.Boolean(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(value IS NULL) = missing", name="economic_missing_value"),
    )
    op.create_index(
        "economic_latest",
        "economic_observations",
        ["workspace_id", "series_key", "observation_date", "id"],
    )
    op.create_table(
        "economic_refresh_state",
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), primary_key=True),
        sa.Column("provider", sa.String(20), primary_key=True),
        sa.Column("last_attempt", sa.DateTime(timezone=True)),
        sa.Column("last_success", sa.DateTime(timezone=True)),
        sa.Column("next_due", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(200)),
    )


def downgrade() -> None:
    """Remove economics storage only."""
    op.drop_table("economic_refresh_state")
    op.drop_table("economic_observations")
