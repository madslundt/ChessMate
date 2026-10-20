"""Account-owned LLM connections."""
from alembic import op
import sqlalchemy as sa

revision = '8ac412e5b620'
down_revision = '3419be9c3cd5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('llm_connections',
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('base_url', sa.String(2000), nullable=False),
        sa.Column('model', sa.String(200), nullable=False),
        sa.Column('api_key', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'))


def downgrade():
    op.drop_table('llm_connections')
