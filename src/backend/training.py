"""Authenticated training APIs, exercise grading, and adaptive practice."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal
from uuid import uuid4

import chess
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from .auth import current_user
from .database import get_db
from .engine import EngineUnavailable, engine_service, score_number
from .exercises import CATEGORIES, objective_met, parse_move, public_exercise, read_library, validate_structure, localized_exercise, retry_feedback
from .models import Game, HintUsage, User, now
from .views import ExerciseView, AttemptView, ProgressView
from .training_models import Exercise, ExerciseAttempt, HintEvent, LearningProgress, OpeningLine, TrainingSession

router = APIRouter(tags=["training"])
DB = Annotated[Session, Depends(get_db)]
Player = Annotated[User, Depends(current_user)]


class AttemptRequest(BaseModel):
    moves: list[str] = Field(min_length=1, max_length=16)
    hint_level: int = Field(default=0, ge=0, le=4)


class HintRequest(BaseModel):
    level: int = Field(default=1, ge=1, le=4)


class SessionRequest(BaseModel):
    kind: Literal["daily", "mixed", "tactical", "opening", "endgame", "mistakes", "review", "forks", "pins", "skewers", "middlegame"] = "daily"
    minutes: int = Field(default=5, ge=1, le=60)


def seed_exercises(db: Session) -> None:
    """Idempotent seeds; malformed or unverified imported content never becomes public."""
    for item in read_library():
        if db.get(Exercise, item["id"]) is None:
            validate_structure(item)
            if not item.get("evidence", {}).get("objective_verified"):
                raise ValueError(f"Missing verification evidence for {item['id']}")
            db.add(Exercise(id=item["id"], category=item["category"], data=item))
    db.commit()


def accessible(db: Session, user: User, exercise_id: str) -> Exercise:
    item = db.get(Exercise, exercise_id)
    if item is None or item.owner_id not in (None, user.id):
        raise HTTPException(404, "Exercise not found")
    return item


@router.get("/exercises", response_model=list[ExerciseView])
def list_exercises(db: DB, user: Player, category: str | None = Query(None, max_length=30), language: Literal["en", "da"] | None = None) -> list[dict]:
    query = select(Exercise).where(or_(Exercise.owner_id.is_(None), Exercise.owner_id == user.id))
    if category:
        if category not in CATEGORIES:
            raise HTTPException(422, "Unknown exercise category")
        query = query.where(Exercise.category == category)
    return [public_exercise(localized_exercise(x.data, language or user.preferences.get("language", "en"))) for x in db.scalars(query.order_by(Exercise.id))]


@router.get("/exercises/{exercise_id}", response_model=ExerciseView)
def get_exercise(exercise_id: str, db: DB, user: Player) -> dict:
    return public_exercise(localized_exercise(accessible(db, user, exercise_id).data, user.preferences.get("language", "en")))


def _same_result(best: dict, chosen: dict, tolerance: int = 70) -> bool:
    if best.get("mate") is not None and chosen.get("mate") is not None:
        return (best["mate"] > 0) == (chosen["mate"] > 0)
    return score_number(best) - score_number(chosen) <= tolerance


def grade_alternative(board: chess.Board, move: chess.Move, data: dict) -> tuple[bool, dict]:
    if not objective_met(board, move, data["criterion"]):
        return False, {"objective_met": False}
    try:
        best = engine_service.analyze(board, candidates=1, time_ms=350)["candidates"][0]
        played = engine_service.analyze(board, candidates=1, time_ms=350, root_moves=[move])["candidates"][0]
    except EngineUnavailable as exc:
        raise HTTPException(503, "Stockfish is needed to verify this alternative. Retry when the engine is available.") from exc
    return _same_result(best, played), {"best": best, "played": played, "objective_met": True}


def _effective_hints(db: Session, user_id: str, exercise_id: str, requested: int) -> int:
    last_solved = db.scalar(select(ExerciseAttempt.created_at).where(
        ExerciseAttempt.user_id == user_id, ExerciseAttempt.exercise_id == exercise_id,
        ExerciseAttempt.correct.is_(True), ExerciseAttempt.complete.is_(True)
    ).order_by(ExerciseAttempt.created_at.desc()).limit(1))
    query = select(HintEvent.level).where(HintEvent.user_id == user_id, HintEvent.exercise_id == exercise_id)
    if last_solved:
        query = query.where(HintEvent.created_at > last_solved)
    return max([requested, *db.scalars(query).all()])


def update_schedule(db: Session, user_id: str, exercise: Exercise, correct: bool, hint_level: int) -> None:
    progress = db.scalar(select(LearningProgress).where(
        LearningProgress.user_id == user_id, LearningProgress.exercise_id == exercise.id).with_for_update())
    if progress is None:
        progress = LearningProgress(user_id=user_id, exercise_id=exercise.id, topic=exercise.category,
                                    streak=0, interval_days=0)
        db.add(progress)
    progress.last_attempt_at = now()
    if not correct:
        progress.streak, progress.interval_days = 0, 0.04
    elif hint_level:
        progress.streak, progress.interval_days = 0, 1 if hint_level < 4 else 0.25
    else:
        progress.streak += 1
        progress.interval_days = min(60, max(1, progress.interval_days * 2.2))
    progress.due_at = now() + timedelta(days=progress.interval_days)


@router.post("/exercises/{exercise_id}/attempt", response_model=AttemptView)
def attempt_exercise(exercise_id: str, body: AttemptRequest, db: DB, user: Player) -> dict:
    exercise = accessible(db, user, exercise_id)
    data, board = exercise.data, chess.Board(exercise.data["fen"])
    language = user.preferences.get("coach_language", "en")
    expected = data["solution"]
    submitted, correct, evidence = [], True, {}
    if len(body.moves) > len(expected):
        raise HTTPException(422, "Too many moves for this exercise")
    for index, text in enumerate(body.moves):
        try:
            move = parse_move(board, text)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        expected_move = parse_move(board, expected[index])
        submitted.append(move.uci())
        if move != expected_move:
            failure_board, failure_move = board.copy(stack=False), move
            criterion = data["criterion"]
            if index:
                criterion = {"kind": "capture", "min_value": 1} if board.is_capture(expected_move) else {"kind": "engine"}
            failure_criterion = criterion
            if index % 2 == 0 and (len(expected) == 1 or index == len(expected) - 1):
                correct, evidence = grade_alternative(board, move, {**data, "criterion": criterion})
            else:
                correct = False
            board.push(move)
            break
        board.push(move)
    complete = correct and len(body.moves) == len(expected)
    reply = None
    if correct and not complete and len(body.moves) % 2 == 1:
        response = parse_move(board, expected[len(body.moves)])
        reply = response.uci()
        board.push(response)
        complete = len(body.moves) + 1 == len(expected)
    hints = _effective_hints(db, user.id, exercise.id, body.hint_level)
    db.add(ExerciseAttempt(user_id=user.id, exercise_id=exercise.id, topic=exercise.category,
                           moves=submitted, correct=correct, complete=complete, hint_level=hints, evidence=evidence))
    if complete or not correct:
        update_schedule(db, user.id, exercise, correct, hints)
    db.commit()
    lesson = localized_exercise(data, language)
    feedback = (("Godt set. " if language == "da" else "Well spotted. ") + lesson["explanation"]) if complete else (
        ("Trækket passer. Find næste træk i varianten." if language == "da" else "That move fits. Find the next move in the continuation.") if correct else
        retry_feedback(failure_board, failure_move, failure_criterion, evidence, language))
    result = {"correct": correct, "complete": complete, "feedback": feedback,
              "fen": board.fen() if correct else data["fen"], "reply": reply, "hint_level": hints}
    if complete:
        result.update(solution=expected, explanation=lesson["explanation"], evidence=data.get("evidence", {}))
    return result


@router.post("/exercises/{exercise_id}/hint")
def exercise_hint(exercise_id: str, body: HintRequest, db: DB, user: Player) -> dict:
    exercise = accessible(db, user, exercise_id)
    hints = localized_exercise(exercise.data, user.preferences.get("coach_language", "en"))["hints"]
    level = min(body.level, len(hints))
    db.add(HintEvent(user_id=user.id, exercise_id=exercise_id, level=level))
    db.commit()
    result = {"text": hints[level - 1], "level": level}
    if level == 4:
        result["move"] = exercise.data["solution"][0]
    return result


def progress_data(db: Session, user: User) -> dict:
    attempts = db.scalars(select(ExerciseAttempt).where(ExerciseAttempt.user_id == user.id)
                         .order_by(ExerciseAttempt.created_at)).all()
    topics: dict[str, dict] = {t: {"topic": t, "attempts": 0, "correct": 0, "independent": 0} for t in CATEGORIES}
    timeline: dict[str, dict] = defaultdict(lambda: {"attempts": 0, "correct": 0})
    for attempt in attempts:
        if attempt.correct and not attempt.complete:
            continue
        entry = topics[attempt.topic]
        entry["attempts"] += 1
        entry["correct"] += int(attempt.correct)
        entry["independent"] += int(attempt.correct and not attempt.hint_level)
        day = attempt.created_at.date().isoformat()
        timeline[day]["attempts"] += 1
        timeline[day]["correct"] += int(attempt.correct)
    for topic in topics.values():
        topic["accuracy"] = round(topic["correct"] / topic["attempts"], 3) if topic["attempts"] else 0
        topic["strength"] = "developing" if topic["attempts"] < 3 else "strength" if topic["independent"] / topic["attempts"] >= .8 else "practice"
    total, correct = sum(t["attempts"] for t in topics.values()), sum(t["correct"] for t in topics.values())
    games = db.scalars(select(Game).where(Game.user_id == user.id)).all()
    mistakes: dict[str, int] = defaultdict(int)
    games_played = 0
    for game in games:
        board = chess.Board(game.initial_fen)
        for move in game.moves:
            feedback = move.get("feedback") or {}
            if board.turn == (game.player_color == "white") and feedback.get("classification") in ("Mistake", "Blunder"):
                topic = "endgame" if len(board.piece_map()) <= 10 else "opening" if board.fullmove_number <= 10 else "middlegame"
                best_uci = (feedback.get("best") or {}).get("uci")
                if best_uci:
                    try:
                        best_move = parse_move(board, best_uci)
                        for motif_topic, kind in (("forks", "fork"), ("pins", "pin"), ("skewers", "skewer")):
                            if objective_met(board, best_move, {"kind": kind}):
                                topic = motif_topic
                                break
                    except ValueError:
                        pass
                mistakes[topic] += 1
            board.push_uci(move["uci"])
        games_played += bool(game.moves)
    due = db.scalars(select(LearningProgress).where(LearningProgress.user_id == user.id, LearningProgress.due_at <= now())).all()
    ranked = sorted(topics.values(), key=lambda x: (x["accuracy"] if x["attempts"] else .65) - min(.5, mistakes[x["topic"]] * .1))
    recommendations = [{"topic": t["topic"], "reason": (
        "Review this concept after mistakes in your games." if mistakes[t["topic"]] else
        "Strengthen a topic that has been difficult." if t["attempts"] else "Build a foundation with a short lesson."),
        "label": t["topic"].title(), "kind": t["topic"]} for t in ranked[:3]]
    hint_count = len(db.scalars(select(HintEvent.id).where(HintEvent.user_id == user.id)).all())
    hint_count += len(db.scalars(select(HintUsage.id).where(HintUsage.user_id == user.id)).all())
    if user.preferences.get("language") == "da":
        labels = {"forks": "Gafler", "pins": "Bindinger", "skewers": "Spidninger", "opening": "Åbning", "middlegame": "Midtspil", "endgame": "Slutspil"}
        for item in recommendations:
            item.update(label=labels[item["topic"]], reason="Øv et emne med fejl i dine partier." if mistakes[item["topic"]] else "Styrk dette emne med en kort øvelse.")
    return {"games_played": games_played, "attempts": total, "correct": correct,
            "accuracy": round(correct / total, 3) if total else 0, "hints_used": hint_count,
            "topics": list(topics.values()), "recommendations": recommendations, "due_reviews": len(due),
            "game_mistakes": dict(mistakes), "timeline": [{"date": date, **v} for date, v in sorted(timeline.items())]}


@router.get("/progress", response_model=ProgressView)
def get_progress(db: DB, user: Player) -> dict:
    return progress_data(db, user)


@router.post("/training/sessions")
def create_session(body: SessionRequest, db: DB, user: Player) -> dict:
    available = list(db.scalars(select(Exercise).where(or_(Exercise.owner_id.is_(None), Exercise.owner_id == user.id))))
    if body.kind in CATEGORIES:
        available = [x for x in available if x.category == body.kind]
    elif body.kind == "tactical":
        available = [x for x in available if x.category in ("forks", "pins", "skewers")]
    elif body.kind == "mistakes":
        available = [x for x in available if x.source_game_id]
    schedules = {p.exercise_id: p for p in db.scalars(select(LearningProgress).where(LearningProgress.user_id == user.id))}
    current = now()
    weak = {t["topic"]: t["accuracy"] for t in progress_data(db, user)["topics"] if t["attempts"]}
    def priority(exercise: Exercise) -> tuple:
        schedule = schedules.get(exercise.id)
        due = schedule.due_at.replace(tzinfo=timezone.utc) if schedule else None
        return (0 if due and due <= current else 1 if schedule is None else 2,
                weak.get(exercise.category, .6), schedule.streak if schedule else 0, exercise.data["difficulty"], exercise.id)
    if body.kind == "review":
        available = [x for x in available if x.id in schedules]
    ordered = sorted(available, key=priority)
    selected = ordered[:min(20, max(1, body.minutes // 2 + 1))]
    session = TrainingSession(user_id=user.id, kind=body.kind, minutes=body.minutes, exercise_ids=[x.id for x in selected])
    db.add(session)
    db.commit()
    return {"id": session.id, "kind": body.kind, "minutes": body.minutes,
            "exercises": [public_exercise(localized_exercise(x.data, user.preferences.get("language", "en"))) for x in selected]}


@router.post("/games/{game_id}/exercises")
def exercises_from_game(game_id: str, db: DB, user: Player) -> dict:
    game = db.get(Game, game_id)
    if game is None or game.user_id != user.id:
        raise HTTPException(404, "Game not found")
    board, created = chess.Board(game.initial_fen), []
    existing = set(db.scalars(select(Exercise.id).where(Exercise.source_game_id == game_id)))
    for index, played in enumerate(game.moves):
        exercise_id = f"game-{game_id}-{index}"
        reported = played.get("feedback") or {}
        if (board.turn == (game.player_color == "white") and exercise_id not in existing
                and reported.get("classification") in ("Mistake", "Blunder") and len(created) < 5):
            try:
                grade = engine_service.grade(board, chess.Move.from_uci(played["uci"]), time_ms=400)
            except EngineUnavailable as exc:
                raise HTTPException(503, "Stockfish is needed to verify game-derived exercises.") from exc
            best = grade["best"]
            best_move = chess.Move.from_uci(best["uci"])
            if grade["loss_cp"] >= 100 and best_move.uci() != played["uci"]:
                category, criterion = None, None
                for topic, kind in [("forks", "fork"), ("pins", "pin"), ("skewers", "skewer")]:
                    if objective_met(board, best_move, {"kind": kind}):
                        category, criterion = topic, {"kind": kind}
                        break
                if category is None and objective_met(board, best_move, {"kind": "capture", "min_value": 3}):
                    category, criterion = "middlegame", {"kind": "capture", "min_value": 3}
                if category:
                    objective = {"forks": "Create a fork attacking two valuable pieces.",
                                 "pins": "Create an absolute pin against the king.",
                                 "skewers": "Create a skewer through the king.",
                                 "middlegame": "Find the sound capture of a valuable piece."}[category]
                    data = {"id": exercise_id, "title": f"Your game, move {board.fullmove_number}",
                            "category": category, "difficulty": 2, "fen": board.fen(), "objective": objective,
                            "solution": [best_move.uci()], "criterion": criterion,
                            "explanation": "This move meets the stated objective and is preferred by a fresh comparison from the original position. " + best["explanation"],
                            "hints": ["Scan checks, captures, and threats.", objective,
                                      f"Look at the piece on {chess.square_name(best_move.from_square)}.", f"Try {best['san']}."],
                            "tags": [category, "your-games"], "evidence": {**best, "objective_verified": True,
                                "source_game_id": game_id, "ply": index, "original_move": played["uci"], "loss_cp": grade["loss_cp"]}}
                    validate_structure(data)
                    db.add(Exercise(id=exercise_id, category=category, data=data, owner_id=user.id, source_game_id=game_id))
                    created.append(public_exercise(data))
        board.push_uci(played["uci"])
    db.commit()
    return {"exercises": created, "count": len(created), "message": "Only freshly verified, instructive positions become exercises."}


class RepertoireRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: Literal["white", "black"]
    moves: list[str] = Field(min_length=1, max_length=60)
    fen: str = Field(default=chess.STARTING_FEN, max_length=120)


def repertoire_view(line: OpeningLine) -> dict:
    board, sans = chess.Board(line.initial_fen), []
    for text in line.moves:
        move = parse_move(board, text)
        sans.append(board.san(move))
        board.push(move)
    return {"id": line.id, "name": line.name, "color": line.color, "initial_fen": line.initial_fen,
            "moves": line.moves, "san": sans, "fen": board.fen()}


def owned_line(db: Session, user: User, line_id: str) -> OpeningLine:
    line = db.get(OpeningLine, line_id)
    if line is None or line.user_id != user.id:
        raise HTTPException(404, "Opening line not found")
    return line


@router.get("/repertoire")
def list_repertoire(db: DB, user: Player) -> list[dict]:
    return [repertoire_view(line) for line in db.scalars(select(OpeningLine).where(
        OpeningLine.user_id == user.id).order_by(OpeningLine.created_at.desc()))]


@router.post("/repertoire", status_code=201)
def add_repertoire(body: RepertoireRequest, db: DB, user: Player) -> dict:
    try:
        board = chess.Board(body.fen)
        if not board.is_valid() or board.is_game_over():
            raise ValueError("Choose a valid, nonterminal initial position")
        normalized = []
        player_has_move = False
        for text in body.moves:
            player_has_move |= board.turn == (body.color == "white")
            move = parse_move(board, text)
            normalized.append(move.uci())
            board.push(move)
        if not player_has_move:
            raise ValueError("The line needs at least one move for the selected repertoire color")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    line = OpeningLine(user_id=user.id, name=body.name.strip() or "Opening line", color=body.color,
                       initial_fen=chess.Board(body.fen).fen(), moves=normalized)
    db.add(line)
    db.commit()
    return repertoire_view(line)


@router.delete("/repertoire/{line_id}")
def remove_repertoire(line_id: str, db: DB, user: Player) -> dict:
    line = owned_line(db, user, line_id)
    db.execute(delete(Exercise).where(Exercise.owner_id == user.id, Exercise.id.like(f"repertoire-{line_id}-%")))
    db.delete(line)
    db.commit()
    return {"deleted": True}


@router.post("/repertoire/{line_id}/practice")
def practice_repertoire(line_id: str, db: DB, user: Player) -> dict:
    line, selected = owned_line(db, user, line_id), []
    board = chess.Board(line.initial_fen)
    for index, text in enumerate(line.moves):
        move = parse_move(board, text)
        if board.turn == (line.color == "white") and len(selected) < 10:
            exercise_id = f"repertoire-{line.id}-{index}"
            existing = db.get(Exercise, exercise_id)
            if existing:
                selected.append(existing)
            else:
                try:
                    best = engine_service.analyze(board, candidates=1, time_ms=250)["candidates"][0]
                    chosen = engine_service.analyze(board, candidates=1, time_ms=250, root_moves=[move])["candidates"][0]
                except EngineUnavailable as exc:
                    raise HTTPException(503, "Stockfish is needed to verify repertoire exercises.") from exc
                if _same_result(best, chosen):
                    san = board.san(move)
                    data = {"id": exercise_id, "title": f"{line.name} · {board.fullmove_number}",
                            "category": "opening", "difficulty": 2, "fen": board.fen(),
                            "objective": "Find a sound move in this opening repertoire position.",
                            "solution": [move.uci()], "criterion": {"kind": "engine"},
                            "explanation": chosen["explanation"], "tags": ["opening", "repertoire", line.color],
                            "hints": ["Compare central control, development, and king safety.",
                                      "Review your repertoire’s intended continuation.",
                                      f"Look at the piece on {chess.square_name(move.from_square)}.", f"Try {san}."],
                            "evidence": {**chosen, "objective_verified": True, "best": best, "repertoire_id": line.id}}
                    existing = Exercise(id=exercise_id, category="opening", data=data, owner_id=user.id)
                    db.add(existing)
                    selected.append(existing)
        board.push(move)
    session = TrainingSession(user_id=user.id, kind="opening", minutes=max(1, 2 * len(selected)),
                              exercise_ids=[x.id for x in selected])
    db.add(session)
    db.commit()
    return {"id": session.id, "kind": "opening", "minutes": session.minutes,
            "exercises": [public_exercise(localized_exercise(x.data, user.preferences.get("language", "en"))) for x in selected],
            "message": "Only engine-verified sound repertoire moves become exercises."}
