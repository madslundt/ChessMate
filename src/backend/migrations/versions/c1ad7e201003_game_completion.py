"""Retain non-board game results, including resignation and completed PGN imports."""
from alembic import op
import sqlalchemy as sa

revision = "c1ad7e201003"
down_revision = "c1ad7e201002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("games", sa.Column("result_override", sa.String(7), nullable=True))
    op.add_column("games", sa.Column("completion_reason", sa.String(20), nullable=True))


def downgrade():
    op.drop_column("games", "completion_reason")
    op.drop_column("games", "result_override")
