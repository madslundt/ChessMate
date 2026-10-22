"""Daily diary projections and explicitly requested report snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "c1ad7e201002"
down_revision = "c1ad7e201001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("daily_diaries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False), sa.Column("timezone", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "date", name="uq_diary_user_date"))
    op.create_index("ix_daily_diaries_user_id", "daily_diaries", ["user_id"])
    op.create_table("progress_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False), sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_progress_reports_user_id", "progress_reports", ["user_id"])
    op.create_index("ix_reports_user_created", "progress_reports", ["user_id", "created_at"])


def downgrade():
    op.drop_table("progress_reports")
    op.drop_table("daily_diaries")
