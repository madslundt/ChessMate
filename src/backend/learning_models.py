"""Append-only evidence of calculation practice and subsequent learning observations."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, event
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import now, uid


class LearningEvent(Base):
    __tablename__ = "learning_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    topic: Mapped[str] = mapped_column(String(30), index=True)
    fen: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


@event.listens_for(LearningEvent, "before_update")
def immutable_learning_event(_mapper, _connection, _target):
    raise ValueError("Learning events are immutable; append a new observation instead")


class GameLearningAnalysis(Base):
    """Durable outbox and rebuildable game projection, separate from immutable move events."""
    __tablename__ = "game_learning_analyses"
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(default=1)
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PlayerLearningState(Base):
    """A bounded-window projection; immutable evidence remains in game/learning events."""
    __tablename__ = "player_learning_states"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
