"""Local owner, workspace, and account."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    op.create_table("owners", sa.Column("id", sa.Uuid(), primary_key=True))
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("owners.id"), nullable=False, unique=True),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False, unique=True
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 80", name="account_name"),
        sa.CheckConstraint(
            "base_currency IN ('USD','EUR','GBP','CAD','AUD','JPY','CHF','HKD','SGD')",
            name="account_currency",
        ),
    )
    op.execute("INSERT INTO owners VALUES ('00000000-0000-4000-8000-000000000001')")
    op.execute(
        "INSERT INTO workspaces VALUES ('00000000-0000-4000-8000-000000000002', "
        "'00000000-0000-4000-8000-000000000001')"
    )


def downgrade():
    op.drop_table("accounts")
    op.drop_table("workspaces")
    op.drop_table("owners")
