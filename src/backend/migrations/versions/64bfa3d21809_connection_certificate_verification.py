"""Per-connection certificate verification, enabled for all existing connections."""
from alembic import op
import sqlalchemy as sa

revision = '64bfa3d21809'
down_revision = '8ac412e5b620'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('llm_connections', sa.Column('verify_tls', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column('llm_connections', 'verify_tls')
