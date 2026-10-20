"""Private branch provenance for multi-move exercises and their progressive hints."""
import chess
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .exercises import parse_move
from .training_models import Exercise, ExerciseAttempt
from .training_generation import verified_continuation


def expected_line(db: Session, user_id: str, exercise: Exercise, branch_id: str | None) -> list[str]:
    if branch_id is None: return list(exercise.data["solution"])
    attempt = db.get(ExerciseAttempt, branch_id)
    if attempt is None or attempt.user_id != user_id or attempt.exercise_id != exercise.id or not attempt.correct:
        raise HTTPException(404, "Exercise branch not found")
    return list(attempt.evidence.get("accepted_solution", exercise.data["solution"]))


def alternative_line(board: chess.Board, candidate: dict, prefix: list[str], exercise: Exercise, complexity: str) -> list[str]:
    continuation, _ = verified_continuation(board, candidate, exercise.category, complexity)
    remaining = 15 - len(prefix)
    continuation = continuation[:remaining]
    if len(continuation) % 2 == 0: continuation.pop()
    return prefix + continuation
