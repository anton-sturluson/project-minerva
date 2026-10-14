"""Store sourced managers and public quarterly filing snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str = "0013"


def upgrade() -> None:
    """Add research storage without changing portfolio records."""
    op.create_table(
        "research_managers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("profile", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("workspace_id", "slug"),
        sa.UniqueConstraint("workspace_id", "cik"),
    )
    op.create_table(
        "research_filings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("manager_id", sa.Uuid(), sa.ForeignKey("research_managers.id"), nullable=False),
        sa.Column("accession", sa.String(24), nullable=False),
        sa.Column("report_period", sa.Date(), nullable=False),
        sa.Column("filed_date", sa.Date(), nullable=False),
        sa.Column("form", sa.String(12), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("amendment_type", sa.String(40)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("manager_id", "accession"),
    )
    op.create_table(
        "research_holdings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("filing_id", sa.Uuid(), sa.ForeignKey("research_filings.id"), nullable=False),
        sa.Column("cusip", sa.String(9), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("security_class", sa.Text(), nullable=False),
        sa.Column("put_call", sa.String(4), nullable=False),
        sa.Column("share_type", sa.String(3), nullable=False),
        sa.Column("quantity", sa.Numeric(30, 8), nullable=False),
        sa.Column("value_usd", sa.Numeric(30, 2), nullable=False),
        sa.UniqueConstraint("filing_id", "cusip", "put_call", "share_type"),
        sa.CheckConstraint("quantity >= 0 AND value_usd >= 0", name="research_nonnegative"),
    )


def downgrade() -> None:
    """Remove public research snapshots."""
    op.drop_table("research_holdings")
    op.drop_table("research_filings")
    op.drop_table("research_managers")
