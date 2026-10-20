from typing import Literal

import chess
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GameCreate(Input):
    mode: Literal["computer", "training", "analysis"] = "training"
    player_color: Literal["white", "black"] = "white"
    difficulty: int = Field(default=2, ge=1, le=5)
    fen: str | None = Field(default=None, max_length=120)
    pgn: str | None = Field(default=None, max_length=100000)


class Revision(Input):
    revision: int = Field(ge=0)


class MoveRequest(Revision):
    move: str = Field(min_length=2, max_length=12)


class PositionRequest(Input):
    fen: str = Field(default=chess.STARTING_FEN, max_length=120)
    moves: list[str] = Field(default_factory=list, max_length=200)
    time_ms: int = Field(default=250, ge=50, le=3000)
    depth: int | None = Field(default=None, ge=1, le=24)
    candidates: int = Field(default=3, ge=1, le=3)


class HintRequest(PositionRequest):
    level: int = Field(default=1, ge=1, le=4)
    language: Literal["en", "da"] = "en"


class ChatMessage(Input):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class CoachRequest(PositionRequest):
    question: str = Field(min_length=1, max_length=2000)
    game_id: str | None = Field(default=None, max_length=36)
    revision: int | None = Field(default=None, ge=0)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)
    language: Literal["en", "da"] | None = None
    explore: bool = False


class Preferences(Input):
    language: Literal["en", "da"] = "en"
    coach_language: Literal["en", "da"] = "en"
    theme: Literal["dark", "light", "system"] = "light"
    player_color: Literal["white", "black"] = "white"
    difficulty: int = Field(default=2, ge=1, le=5)
    orientation: Literal["white", "black", "player"] = "player"
    board_theme: Literal["sage", "wood", "blue"] = "sage"
    piece_style: Literal["classic", "modern"] = "classic"
    auto_computer: bool = True
    show_legal_moves: bool = True
    show_evaluation: bool = False
    show_evaluation_bar: bool = False
    coaching_mode: Literal["independent", "guided", "learning", "socratic"] = "guided"
    feedback: Literal["none", "short", "detailed", "mistakes"] = "short"
    feedback_frequency: Literal["all", "mistakes"] = "all"
    show_alternatives: bool = False
    hide_best_moves: bool = True
    guided_questions: bool = True
    complexity: Literal["beginner", "intermediate"] = "beginner"
    max_explanation_length: int = Field(default=120, ge=30, le=400)
    progressive_hints: bool = True
    analysis_time_ms: int = Field(default=250, ge=50, le=3000)
    analysis_depth: int | None = Field(default=None, ge=1, le=24)
    candidate_count: int = Field(default=3, ge=1, le=3)
    show_pv: bool = False

    @field_validator("language", "coach_language", mode="before")
    @classmethod
    def normalize_language(cls, value):
        return {"English": "en", "Danish": "da"}.get(value, value)
