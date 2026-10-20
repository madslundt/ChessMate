from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def uid() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    # Legacy column retained for existing databases; profile selection does not use passwords.
    password_hash: Mapped[str] = mapped_column(String(256), default="")
    preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LlmConnection(Base):
    __tablename__ = "llm_connections"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    base_url: Mapped[str] = mapped_column(String(2000), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    api_key: Mapped[str] = mapped_column(Text, default="")
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class SpeechSettings(Base):
    __tablename__ = "speech_settings"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    stt_mode: Mapped[str] = mapped_column(String(10), default="browser", server_default="browser")
    stt_base_url: Mapped[str] = mapped_column(String(2000), default="")
    stt_model: Mapped[str] = mapped_column(String(200), default="")
    stt_api_key: Mapped[str] = mapped_column(Text, default="")
    tts_mode: Mapped[str] = mapped_column(String(10), default="browser", server_default="browser")
    tts_base_url: Mapped[str] = mapped_column(String(2000), default="")
    tts_model: Mapped[str] = mapped_column(String(200), default="")
    tts_voice: Mapped[str] = mapped_column(String(200), default="alloy", server_default="alloy")
    tts_api_key: Mapped[str] = mapped_column(Text, default="")
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Game(Base):
    __tablename__ = "games"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    initial_fen: Mapped[str] = mapped_column(String(120))
    moves: Mapped[list] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(String(20), default="training")
    player_color: Mapped[str] = mapped_column(String(5), default="white")
    difficulty: Mapped[int] = mapped_column(Integer, default=2)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    __mapper_args__ = {"version_id_col": revision, "version_id_generator": False}


class GameEvent(Base):
    """Append-only game actions; undo retains the original move evidence."""
    __tablename__ = "game_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CoachingMessage(Base):
    __tablename__ = "coaching_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    game_id: Mapped[str | None] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=True, index=True)
    fen: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PositionAnalysis(Base):
    __tablename__ = "position_analyses"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    fen: Mapped[str] = mapped_column(String(120), index=True)
    evidence: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class HintUsage(Base):
    __tablename__ = "hint_usage"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    fen: Mapped[str] = mapped_column(String(120))
    level: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
