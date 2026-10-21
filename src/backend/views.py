"""Public response contracts; internal evidence remains extensible and server-owned."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .schemas import Preferences


class View(BaseModel):
    model_config = ConfigDict(extra="allow")


class UserView(View):
    id: str
    name: str
    preferences: Preferences


class MoveView(View):
    uci: str
    san: str
    fen: str
    before_fen: str | None = None
    timeline_revision: int | None = None
    feedback: dict[str, Any] | None = None


class GameView(View):
    id: str
    fen: str
    initial_fen: str
    moves: list[MoveView]
    revision: int
    can_redo: bool = False
    mode: Literal["computer", "training", "analysis"]
    player_color: Literal["white", "black"]
    difficulty: int
    created_at: str
    status: str
    result: str
    turn: Literal["white", "black"]
    legal_moves: list[str]
    check: bool


class CandidateView(View):
    uci: str
    san: str
    cp: int | None
    mate: int | None
    white_cp: int | None
    white_mate: int | None
    pv: list[str]
    pv_uci: list[str]
    depth: int
    facts: dict[str, Any]
    explanation: str
    reply: str | None
    risk: str


class AnalysisView(View):
    fen: str
    perspective: Literal["white", "black"]
    candidates: list[CandidateView]
    observations: dict[str, Any]
    source: str
    analysis_key: str | None = None
    base_fen: str | None = None
    moves: list[str] = Field(default_factory=list)
    terminal: str | None = None


class HintView(View):
    fen: str
    level: int
    text: str
    highlight_square: str | None = None
    highlight_move: str | None = None


class ExerciseView(BaseModel):
    id: str
    title: str
    category: Literal["forks", "pins", "skewers", "opening", "middlegame", "endgame"]
    difficulty: int
    fen: str
    objective: str
    description: str
    tags: list[str]
    move_count: int = 1
    source_game_id: str | None = None


class AttemptView(View):
    correct: bool
    complete: bool
    feedback: str
    fen: str
    reply: str | None
    hint_level: int


class TopicView(View):
    topic: str
    attempts: int
    correct: int
    accuracy: float
    independent: int
    strength: str


class GamePerformanceView(View):
    game_id: str
    date: str
    assessed_moves: int
    sound_moves: int
    errors: int
    sound_rate: float


class ProgressView(View):
    games_played: int
    attempts: int
    correct: int
    accuracy: float
    hints_used: int
    topics: list[TopicView]
    recommendations: list[dict[str, Any]]
    due_reviews: int
    game_mistakes: dict[str, int]
    timeline: list[dict[str, Any]]
    game_performance: list[GamePerformanceView] = Field(default_factory=list)
