"""Add durable automatic learning and retain unknown assistance for historical games."""
from alembic import op
import sqlalchemy as sa

revision = "c1ad7e201001"
down_revision = "91b4e2a6c730"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("games", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("games", sa.Column("difficulty_mode", sa.String(10), server_default="manual", nullable=False))
    op.add_column("games", sa.Column("learning_source", sa.String(10), server_default="game", nullable=False))
    op.add_column("games", sa.Column("assistance_tracked", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("games", sa.Column("training_context", sa.JSON(), nullable=True))
    op.create_index("ix_games_user_completed", "games", ["user_id", "completed_at"])
    op.create_table("game_learning_analyses",
        sa.Column("game_id", sa.String(36), sa.ForeignKey("games.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(200), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    for column in ("user_id", "status", "next_attempt_at"):
        op.create_index(f"ix_game_learning_analyses_{column}", "game_learning_analyses", [column])
    op.create_table("player_learning_states",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("player_learning_states")
    op.drop_table("game_learning_analyses")
    op.drop_index("ix_games_user_completed", table_name="games")
    for column in ("training_context", "assistance_tracked", "learning_source", "difficulty_mode", "completed_at"):
        op.drop_column("games", column)
