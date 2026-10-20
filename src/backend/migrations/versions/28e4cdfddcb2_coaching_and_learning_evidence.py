"""Add persistent coaching provenance, discovery state, and learning events."""
from alembic import op
import sqlalchemy as sa

revision = '28e4cdfddcb2'
down_revision = '64bfa3d21809'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('learning_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('topic', sa.String(length=30), nullable=False),
    sa.Column('fen', sa.String(length=120), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_learning_events_created_at'), 'learning_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_learning_events_kind'), 'learning_events', ['kind'], unique=False)
    op.create_index(op.f('ix_learning_events_topic'), 'learning_events', ['topic'], unique=False)
    op.create_index(op.f('ix_learning_events_user_id'), 'learning_events', ['user_id'], unique=False)
    op.create_table('coaching_states',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('game_id', sa.String(length=36), nullable=True),
    sa.Column('fen', sa.String(length=120), nullable=False),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_coaching_states_fen'), 'coaching_states', ['fen'], unique=False)
    op.create_index(op.f('ix_coaching_states_game_id'), 'coaching_states', ['game_id'], unique=False)
    op.create_index(op.f('ix_coaching_states_user_id'), 'coaching_states', ['user_id'], unique=False)
    op.create_table('coaching_evidence',
    sa.Column('message_id', sa.String(length=36), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['coaching_messages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('message_id')
    )

def downgrade():
    op.drop_table('coaching_evidence')
    op.drop_index(op.f('ix_coaching_states_user_id'), table_name='coaching_states')
    op.drop_index(op.f('ix_coaching_states_game_id'), table_name='coaching_states')
    op.drop_index(op.f('ix_coaching_states_fen'), table_name='coaching_states')
    op.drop_table('coaching_states')
    op.drop_index(op.f('ix_learning_events_user_id'), table_name='learning_events')
    op.drop_index(op.f('ix_learning_events_topic'), table_name='learning_events')
    op.drop_index(op.f('ix_learning_events_kind'), table_name='learning_events')
    op.drop_index(op.f('ix_learning_events_created_at'), table_name='learning_events')
    op.drop_table('learning_events')
