"""Add selectable speech synthesis output format."""
from alembic import op
import sqlalchemy as sa


revision = "91b4e2a6c730"
down_revision = "7f13a04c2d91"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "speech_settings",
        sa.Column("tts_format", sa.String(10), server_default="mp3", nullable=False),
    )


def downgrade():
    op.drop_column("speech_settings", "tts_format")
