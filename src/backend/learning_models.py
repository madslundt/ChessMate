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
