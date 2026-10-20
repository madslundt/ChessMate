"""Cancellable whole-game teaching analysis with deeper verification of critical decisions."""
import copy
import time

import chess
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analysis_jobs import JobFailed, analysis_jobs
from .auth import current_user
from .chess_tools import parse_board, parse_move
from .database import get_db
from .engine import AnalysisCancelled, engine_service
from .games import board_for, commit_event, feedback_for_learner, owned_game
from .models import Game, User
from .schemas import GameAnalysisJobRequest, Preferences

router = APIRouter(prefix="/games", tags=["Games"])


@router.post("/{game_id}/analysis-jobs", status_code=202)
def start_game_analysis(game_id: str, data: GameAnalysisJobRequest, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    game = owned_game(db, game_id, user)
    if game.revision != data.revision: raise HTTPException(409, "The game changed; refresh before analysis")
    if data.start_ply > len(game.moves): raise HTTPException(422, "Analysis starts beyond the game")
    records = copy.deepcopy(game.moves)
    initial_fen, owner, player_color = game.initial_fen, user.id, game.player_color
    preferences = Preferences.model_validate(user.preferences or {})
    critical_budget = data.critical_time_ms or preferences.deep_analysis_time_ms
    fen = board_for(game).fen()
    # Resolve at request time so deployments and isolated test sessions use the same factory.
    from .main import SessionLocal
    factory = SessionLocal
    def work(job):
        started = time.monotonic()
        board = parse_board(initial_fen, [record["uci"] for record in records[:data.start_ply]])
        analyzed, critical, next_ply = 0, 0, data.start_ply
        changes = []
        turning_points = []
        for index in range(data.start_ply, len(records)):
            if job.cancel.is_set(): raise AnalysisCancelled("Analysis cancelled")
            if time.monotonic() - started > 900: break
            record = records[index]
            move = parse_move(board, record["uci"])
            feedback = record.get("feedback") or {}
            changed = False
            if data.refresh or feedback.get("fen") != board.fen() or feedback.get("confidence") in (None, "unavailable", "limited", "unstable_search"):
                feedback = engine_service.grade(board, move, time_ms=data.time_ms, language=preferences.coach_language,
                    complexity=preferences.complexity, cancel_event=job.cancel)
                changed = True
            is_critical = feedback.get("classification") in ("Mistake", "Blunder") or feedback.get("win_chance_loss", 0) is not None and feedback.get("win_chance_loss", 0) >= .15
            best_mate, played_mate = feedback.get("best", {}).get("mate"), feedback.get("played", {}).get("mate")
            if best_mate is not None and best_mate > 0 and not (played_mate is not None and played_mate > 0): is_critical = True
            if is_critical and (data.refresh or feedback.get("analysis_mode") != "deep"):
                analysis_jobs.set_progress(job, stage="verifying_critical", current_ply=index + 1)
                feedback = engine_service.grade(board, move, time_ms=critical_budget, language=preferences.coach_language,
                    complexity=preferences.complexity, mode="deep", cancel_event=job.cancel)
                feedback = {**feedback, "critical_verified": True, "verification_budget_ms": critical_budget}
                changed = True
            if feedback.get("critical_verified"): critical += 1
            if changed:
                record["feedback"] = feedback_for_learner(feedback, "white" if board.turn else "black", player_color, preferences.coach_language)
                changes.append({"ply": index + 1, "feedback": record["feedback"]})
                analyzed += 1
            if feedback.get("classification") in ("Mistake", "Blunder", "Inaccuracy"):
                turning_points.append({"ply": index + 1, "san": record["san"], "classification": feedback["classification"],
                                       "loss_cp": feedback.get("loss_cp", 0), "fen": board.fen()})
            board.push(move)
            next_ply = index + 1
            analysis_jobs.set_progress(job, completed=next_ply, total=len(records), critical_verified=critical, stage="analyzing", current_ply=next_ply)
        if job.cancel.is_set(): raise AnalysisCancelled("Analysis cancelled")
        with factory() as session:
            stored = session.scalar(select(Game).where(Game.id == game_id, Game.user_id == owner))
            if not stored or stored.revision != data.revision:
                raise JobFailed("The game changed during analysis; restart from its current revision")
            if analyzed:
                stored.moves = records
                try:
                    commit_event(session, stored, "analysis", {"start_ply": data.start_ply, "end_ply": next_ply,
                        "critical_verified": critical, "assessments": changes})
                except HTTPException:
                    raise JobFailed("The game changed during analysis; restart from its current revision") from None
            revision = stored.revision
        analysis_jobs.set_progress(job, revision=revision, completed=next_ply, stage="complete")
        return {"game_id": game_id, "revision": revision, "analyzed": analyzed, "total": len(records),
                "next_ply": next_ply, "complete": next_ply == len(records), "critical_verified": critical,
                "turning_points": sorted(turning_points, key=lambda item: item["loss_cp"], reverse=True)[:10]}
    job = analysis_jobs.submit_work(owner, fen, work, {"game_id": game_id, "revision": data.revision,
        "completed": data.start_ply, "total": len(records), "critical_verified": 0, "stage": "queued"})
    return analysis_jobs.snapshot(owner, job.id)
