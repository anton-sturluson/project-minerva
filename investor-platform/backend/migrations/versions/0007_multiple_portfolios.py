"""Allow independently named portfolios inside an owned workspace."""

from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade():
    op.drop_constraint("accounts_workspace_id_key", "accounts", type_="unique")
    op.create_unique_constraint("account_workspace_name", "accounts", ["workspace_id", "name"])


def downgrade():
    # PostgreSQL refuses this downgrade while multiple portfolios exist; never drop their data.
    op.drop_constraint("account_workspace_name", "accounts", type_="unique")
    op.create_unique_constraint("accounts_workspace_id_key", "accounts", ["workspace_id"])
