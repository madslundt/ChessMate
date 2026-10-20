"""Per-profile OpenAI-compatible speech provider settings."""
from alembic import op
import sqlalchemy as sa


revision = "7f13a04c2d91"
down_revision = "28e4cdfddcb2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "speech_settings",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("stt_mode", sa.String(10), server_default="browser", nullable=False),
        sa.Column("stt_base_url", sa.String(2000), nullable=False),
        sa.Column("stt_model", sa.String(200), nullable=False),
        sa.Column("stt_api_key", sa.Text(), nullable=False),
        sa.Column("tts_mode", sa.String(10), server_default="browser", nullable=False),
        sa.Column("tts_base_url", sa.String(2000), nullable=False),
        sa.Column("tts_model", sa.String(200), nullable=False),
        sa.Column("tts_voice", sa.String(200), server_default="alloy", nullable=False),
        sa.Column("tts_api_key", sa.Text(), nullable=False),
        sa.Column("verify_tls", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade():
    op.drop_table("speech_settings")
