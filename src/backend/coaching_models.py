"""Persisted, position-scoped coaching provenance and learner discoveries."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import now


class CoachingEvidence(Base):
    __tablename__ = "coaching_evidence"
    message_id: Mapped[str] = mapped_column(ForeignKey("coaching_messages.id", ondelete="CASCADE"), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class CoachingState(Base):
    __tablename__ = "coaching_states"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    game_id: Mapped[str | None] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=True, index=True)
    fen: Mapped[str] = mapped_column(String(120), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __mapper_args__ = {"version_id_col": revision}
