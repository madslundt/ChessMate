"""Position-bound calculation coaching; predicted moves never change saved games."""
import asyncio
import threading
from typing import Any, Literal

import chess
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .chess_tools import parse_board, parse_move
from .engine import engine_service
from .database import get_db
from .learning_evidence import observed_skills, position_key, topic_for, utc_iso
from .learning_models import LearningEvent
from .models import HintUsage, User
from .schemas import Input

router = APIRouter(tags=["Coaching"])
slots = threading.BoundedSemaphore(2)


class CalculationRequest(Input):
    fen: str = Field(max_length=120)
    moves: list[str] = Field(min_length=1, max_length=64)
    time_ms: int = Field(default=250, ge=50, le=500)
    language: Literal["en", "da"] = "en"
    expected_evaluation: Literal["winning", "balanced", "losing"] | None = None
    hint_level: int = Field(default=0, ge=0, le=4)


class CalculationStep(Input):
    ply: int
    fen: str
    move: str
    san: str
    role: Literal["candidate", "opponent_response", "continuation"]
    classification: str
    confidence: str
    best_move: str | None
    reply: str | None
    missed_forcing_move: str | None
    explanation: str
    skills: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class CalculationResult(Input):
    fen: str
    final_fen: str
    text: str
    first_inaccuracy_ply: int | None
    steps: list[CalculationStep]
    final_analysis: dict[str, Any]
    final_evaluation: Literal["winning", "balanced", "losing"] | None
    assessment_agrees: bool | None
    event_id: str
    correct: bool | None
    accuracy: float | None
    independent: bool
    hint_level: int
    retry_count: int
    topic: str


class CalculationHistoryEntry(Input):
    id: str
    fen: str
    created_at: str
    topic: str
    moves: list[str]
    steps: list[CalculationStep]
    correct: bool | None
    accuracy: float | None
    first_inaccuracy_ply: int | None
    independent: bool
    hint_level: int
    retry_count: int
    assessment_agrees: bool | None
    expected_evaluation: Literal["winning", "balanced", "losing"] | None
    final_evaluation: Literal["winning", "balanced", "losing"] | None


def history_entry(event: LearningEvent) -> dict:
    return {"id": event.id, "fen": event.fen, "created_at": utc_iso(event.created_at), "topic": event.topic,
        **{key: event.payload[key] for key in ("moves", "steps", "correct", "accuracy", "first_inaccuracy_ply", "independent", "hint_level", "retry_count", "assessment_agrees", "expected_evaluation", "final_evaluation")}}


@router.get("/calculation/attempts", response_model=list[CalculationHistoryEntry])
def calculation_history(limit: int = Query(20, ge=1, le=100), user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    events = db.scalars(select(LearningEvent).where(LearningEvent.user_id == user.id,
        LearningEvent.kind == "calculation_attempt").order_by(LearningEvent.created_at.desc()).limit(limit)).all()
    return [history_entry(event) for event in events]


@router.get("/calculation/attempts/{event_id}", response_model=CalculationHistoryEntry)
def get_calculation_attempt(event_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    event = db.get(LearningEvent, event_id)
    if event is None or event.user_id != user.id or event.kind != "calculation_attempt":
        raise HTTPException(404, "Calculation attempt not found")
    return history_entry(event)


def record_attempt(db: Session, user: User, data: CalculationRequest, result: dict) -> None:
    key = position_key(result["fen"])
    previous = db.execute(select(LearningEvent.fen, LearningEvent.created_at,
        LearningEvent.payload["correct"].as_boolean().label("correct")).where(LearningEvent.user_id == user.id,
        LearningEvent.kind == "calculation_attempt").order_by(LearningEvent.created_at.desc())).all()
    retries, last_solve = 0, None
    for event in previous:
        if position_key(event.fen) != key: continue
        if event.correct is True:
            last_solve = event.created_at
            break
        retries += int(event.correct is False)
    hints = select(HintUsage).where(HintUsage.user_id == user.id)
    if last_solve: hints = hints.where(HintUsage.created_at > last_solve)
    hint_level = max([data.hint_level, *[hint.level for hint in db.scalars(hints) if position_key(hint.fen) == key]])
    assessed = [step for step in result["steps"] if step["classification"] != "Uncertain"]
    accurate = sum(step["classification"] not in ("Inaccuracy", "Mistake", "Blunder") for step in assessed)
    uncertain = len(assessed) != len(result["steps"])
    correct = False if result["first_inaccuracy_ply"] or result["assessment_agrees"] is False else None if uncertain else True
    first_step = result["steps"][0]
    topic_move = (first_step["evidence"].get("best") or {}).get("uci") if result["first_inaccuracy_ply"] == 1 else None
    topic = topic_for(chess.Board(result["fen"]), chess.Move.from_uci(topic_move or first_step["move"]))
    payload = {"version": 1, "position_key": key, "perspective": "white" if chess.Board(result["fen"]).turn else "black", "moves": [step["move"] for step in result["steps"]], "steps": result["steps"],
        "first_inaccuracy_ply": result["first_inaccuracy_ply"], "correct": correct,
        "accuracy": round(accurate / len(assessed), 3) if assessed else None,
        "assessed_plies": len(assessed), "accurate_plies": accurate,
        "hint_level": hint_level, "retry_count": retries, "independent": correct is True and not hint_level and not retries,
        "assessment_agrees": result["assessment_agrees"], "expected_evaluation": data.expected_evaluation,
        "final_evaluation": result["final_evaluation"], "final_fen": result["final_fen"],
        "difficulty": {"beginner": 1, "intermediate": 2, "advanced": 3}.get(user.preferences.get("complexity", "beginner"), 1)}
    event = LearningEvent(user_id=user.id, kind="calculation_attempt", topic=topic, fen=result["fen"], payload=payload)
    db.add(event)
    db.commit()
    result.update(event_id=event.id, topic=topic, **{key: payload[key] for key in ("correct", "accuracy", "independent", "hint_level", "retry_count")})


async def engine_work(operation, *args, **kwargs):
    """Keep capacity reserved until a canceled request's engine thread actually exits."""
    worker = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if worker.done() and not worker.cancelled(): worker.exception()
        raise


@router.post("/calculation", response_model=CalculationResult)
async def analyze_calculation(data: CalculationRequest, request: Request,
                              _user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try:
        board = parse_board(data.fen)
        # Validate the ENTIRE line before spending any engine resources.
        checked = board.copy()
        moves = []
        for value in data.moves:
            move = parse_move(checked, value)
            moves.append(move.uci())
            checked.push(move)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not slots.acquire(blocking=False):
        raise HTTPException(503, "Calculation coach is busy; retry shortly")
    try:
        root_color, steps, first = board.turn, [], None
        for index, value in enumerate(moves):
            if await request.is_disconnected():
                raise HTTPException(409, "Calculation canceled")
            move = parse_move(board, value)
            feedback = await engine_work(engine_service.grade, board.copy(), move,
                                               time_ms=data.time_ms, language=data.language)
            best = feedback.get("best") or {}
            facts = best.get("facts") or {}
            inaccurate = feedback["classification"] in ("Inaccuracy", "Mistake", "Blunder")
            preferred = chess.Move.from_uci(best["uci"]) if best.get("uci") else move
            skills = set(observed_skills(board, preferred, feedback)) | set(observed_skills(board, move, feedback))
            if index % 2: skills.add("calculation_response")
            if inaccurate and first is None: first = index + 1
            steps.append({"ply": index + 1, "fen": board.fen(), "move": value, "san": board.san(move),
                          "role": "candidate" if index == 0 else "opponent_response" if index % 2 else "continuation",
                          "classification": feedback["classification"], "confidence": feedback["confidence"],
                          "best_move": best.get("uci"), "reply": (feedback.get("played") or {}).get("reply"),
                          "missed_forcing_move": best.get("uci") if inaccurate and (facts.get("check") or facts.get("capture")) else None,
                          "explanation": feedback["text"], "skills": sorted(skills),
                          "evidence": {key: feedback.get(key) for key in ("best", "played", "loss_cp", "search_depth", "confidence")}})
            board.push(move)
        analysis = await engine_work(engine_service.analyze, board.copy(), time_ms=data.time_ms)
        best = next(iter(analysis.get("candidates", [])), {})
        cp, mate = best.get("cp"), best.get("mate")
        sign = 1 if board.turn == root_color else -1
        value = sign * (100000 if mate is not None and mate > 0 else -100000 if mate is not None and mate < 0 else cp or 0)
        outcome = board.outcome(claim_draw=True)
        if outcome:
            evaluation = "balanced" if outcome.winner is None else "winning" if outcome.winner == root_color else "losing"
        elif best:
            evaluation = "winning" if value >= 200 else "losing" if value <= -200 else "balanced"
        else:
            evaluation = None
        da = data.language == "da"
        if first:
            step = steps[first - 1]
            role = ("modstanderens svar" if da else "the opponent's response") if first % 2 == 0 else ("dit træk" if da else "your move")
            text = (f"Den første svagere forudsigelse er halvtræk {first}, {role}: {step['san']}. " if da else
                    f"The first weaker prediction is ply {first}, {role}: {step['san']}. ") + step["explanation"]
        elif any(s["classification"] == "Uncertain" for s in steps):
            text = "Varianten er lovlig, men mindst én vurdering er usikker. Undersøg den med dybere analyse." if da else "The line is legal, but at least one assessment is uncertain. Examine it with deeper analysis."
        else:
            text = ("Alle forudsagte træk er lovlige, og søgningen fandt ingen klar fejl. Det beviser ikke, at varianten er tvungen." if da else
                    "All predicted moves are legal and the search found no clear error. This does not prove the line is forced.")
        agrees = None if data.expected_evaluation is None or evaluation is None else data.expected_evaluation == evaluation
        if agrees is False:
            text += " Din vurdering af slutstillingen afviger fra søgningens estimat." if da else " Your assessment of the final position differs from the search estimate."
        result = {"fen": data.fen, "final_fen": board.fen(), "text": text, "first_inaccuracy_ply": first,
                "steps": steps, "final_analysis": analysis, "final_evaluation": evaluation, "assessment_agrees": agrees}
        if await request.is_disconnected(): raise HTTPException(409, "Calculation canceled")
        record_attempt(db, _user, data, result)
        return result
    finally:
        slots.release()
