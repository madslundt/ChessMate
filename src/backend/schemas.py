from typing import Literal

import chess
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class GameAnalysisRequest(Revision):
    start_ply: int = Field(default=0, ge=0, le=2000)
    limit: int = Field(default=8, ge=1, le=20)
    time_ms: int = Field(default=250, ge=50, le=1000)
    refresh: bool = False


class GameAnalysisJobRequest(Revision):
    start_ply: int = Field(default=0, ge=0, le=2000)
    time_ms: int = Field(default=250, ge=50, le=1000)
    critical_time_ms: int | None = Field(default=None, ge=5000, le=20000)
    refresh: bool = False


class PositionRequest(Input):
    fen: str = Field(default=chess.STARTING_FEN, max_length=120)
    moves: list[str] = Field(default_factory=list, max_length=200)
    time_ms: int = Field(default=250, ge=50, le=20000)
    mode: Literal["quick", "deep"] = "quick"
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
    teaching_mode: Literal["guided", "direct"] | None = None


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
    play_mode: Literal["automatic", "coach_first", "independent"] = "automatic"
    explanation_mode: Literal["text", "visual", "both"] = "both"
    visual_arrows: Literal["automatic", "on_request"] = "automatic"
    variation_speed_ms: int = Field(default=1000, ge=400, le=3000)
    highlight_threats: bool = True
    highlight_pieces: bool = True
    animate_variations: bool = True
    return_after_playback: bool = True
    show_legal_moves: bool = True
    show_evaluation: bool = False
    show_evaluation_bar: bool = False
    coaching_mode: Literal["independent", "guided", "learning", "socratic"] = "guided"
    feedback: Literal["none", "short", "detailed", "mistakes"] = "short"
    feedback_frequency: Literal["all", "mistakes"] = "all"
    show_alternatives: bool = False
    hide_best_moves: bool = True
    guided_questions: bool = True
    complexity: Literal["beginner", "intermediate", "advanced"] = "beginner"
    skill_defaults: bool = True
    max_explanation_length: int = Field(default=120, ge=30, le=400)
    progressive_hints: bool = True
    analysis_time_ms: int = Field(default=250, ge=50, le=3000)
    deep_analysis_time_ms: int = Field(default=5000, ge=5000, le=20000)
    analysis_depth: int | None = Field(default=None, ge=1, le=24)
    candidate_count: int = Field(default=3, ge=1, le=3)
    show_pv: bool = False

    @model_validator(mode="before")
    @classmethod
    def preserve_manual_play(cls, value):
        if isinstance(value, dict) and "play_mode" not in value and value.get("auto_computer") is False:
            return {**value, "play_mode": "coach_first"}
        return value

    @field_validator("language", "coach_language", mode="before")
    @classmethod
    def normalize_language(cls, value):
        return {"English": "en", "Danish": "da"}.get(value, value)
