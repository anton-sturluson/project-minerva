"""Keep import evidence and assumptions with the reconstructed testing account."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"


def upgrade():
    op.add_column("accounts", sa.Column("reconstruction", JSONB(), nullable=True))


def downgrade():
    op.drop_column("accounts", "reconstruction")
