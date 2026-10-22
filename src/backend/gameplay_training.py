"""Authentic positions continued through the normal authoritative game lifecycle."""
import io
from typing import Literal

import chess
import chess.pgn
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import current_user
from .database import get_db
from .games import create_game
from .learning_evidence import position_key
from .learning_models import GameLearningAnalysis, LearningEvent, PlayerLearningState
from .models import Game, GameEvent, User
from .schemas import GameCreate, Input
from .training_models import Exercise
from .exercises import objective_met
from .engine import engine_service

router = APIRouter(prefix="/training", tags=["training"])

# Public-domain complete games; positions retain every piece and all legal rights.
# Motifs are intentionally not asserted without engine evidence. The game provides
# contextual practice, including plausible distractions, instead of a forced line.
CLASSIC_GAMES = [
    ("Morphy–Duke Karl / Count Isouard, Paris 1858", "1. e4 e5 2. Nf3 d6 3. d4 Bg4 4. dxe5 Bxf3 5. Qxf3 dxe5 6. Bc4 Nf6 7. Qb3 Qe7 8. Nc3 c6 9. Bg5 b5 10. Nxb5 cxb5 11. Bxb5+ Nbd7 12. O-O-O Rd8 13. Rxd7 Rxd7 14. Rd1 Qe6 15. Bxd7+ Nxd7 16. Qb8+ Nxb8 17. Rd8#"),
    ("Anderssen–Kieseritzky, London 1851", "1. e4 e5 2. f4 exf4 3. Bc4 Qh4+ 4. Kf1 b5 5. Bxb5 Nf6 6. Nf3 Qh6 7. d3 Nh5 8. Nh4 Qg5 9. Nf5 c6 10. g4 Nf6 11. Rg1 cxb5 12. h4 Qg6 13. h5 Qg5 14. Qf3 Ng8 15. Bxf4 Qf6 16. Nc3 Bc5 17. Nd5 Qxb2 18. Bd6 Bxg1 19. e5 Qxa1+ 20. Ke2 Na6 21. Nxg7+ Kd8 22. Qf6+ Nxf6 23. Be7#"),
]
FOCUS_MAP = {"development": "opening", "positional": "middlegame"}


class TrainingGameRequest(Input):
    focus: Literal["personalized", "mixed", "forks", "pins", "skewers", "defense", "exchanges", "sacrifices", "positional", "development", "pawn_structure", "opening", "middlegame", "endgame"] = "personalized"
    blind: bool = True
    minutes: int = Field(default=10, ge=1, le=60)


def real_positions():
    positions = []
    for title, pgn in CLASSIC_GAMES:
        game = chess.pgn.read_game(io.StringIO(pgn))
        if not game or game.errors: raise ValueError("Invalid built-in training game")
        board = game.board()
        line = list(game.mainline_moves())
        for ply, move in enumerate(line, 1):
            board.push(move)
            if ply >= 8 and ply % 2 == 0 and not board.is_game_over() and len(board.piece_map()) >= 14:
                positions.append({"fen": board.fen(), "source": "classic", "reference": title, "source_ply": ply, "topic": "opening" if ply < 20 else "middlegame", "continuation": [move.uci() for move in line[ply:ply + 2]]})
    return positions


def candidate_positions(db, user, focus):
    # The read budget is fixed independently of total history size.
    analyses = db.scalars(select(GameLearningAnalysis).where(GameLearningAnalysis.user_id == user.id,
        GameLearningAnalysis.status == "completed").order_by(GameLearningAnalysis.updated_at.desc()).limit(100)).all()
    positions = []
    for analysis in analyses:
        for observation in (analysis.evidence or {}).get("observations", []):
            if focus != "mixed" and focus != observation.get("topic") and focus not in observation.get("skills", []): continue
            board = chess.Board(observation["fen"])
            if board.is_valid() and not board.is_game_over() and (len(board.piece_map()) >= 14 or focus == "endgame"):
                positions.append({"fen": board.fen(), "source": "own_game", "reference": analysis.game_id,
                    "source_ply": observation["ply"], "topic": observation.get("topic"),
                    "mistake": observation.get("classification") in ("Mistake", "Blunder")})
    exercises = db.scalars(select(Exercise).where((Exercise.owner_id.is_(None)) | (Exercise.owner_id == user.id)).limit(300)).all()
    for exercise in exercises:
        if focus not in ("mixed", exercise.category): continue
        board = chess.Board(exercise.data["fen"])
        if board.is_valid() and not board.is_game_over() and (len(board.piece_map()) >= 14 or focus == "endgame"):
            positions.append({"fen": board.fen(), "source": "exercise", "reference": exercise.id,
                "source_ply": 0, "topic": exercise.category, "difficulty": exercise.data.get("difficulty", 2)})
    if not positions and focus == "pawn_structure":
        for item in real_positions():
            board = chess.Board(item["fen"])
            pawns = board.pieces(chess.PAWN, board.turn)
            files = [chess.square_file(square) for square in pawns]
            doubled = len(files) != len(set(files))
            isolated = any(not any(neighbor in files for neighbor in (file - 1, file + 1)) for file in files)
            if doubled or isolated:
                positions.append({**item, "topic": focus, "structure_evidence": {"doubled_pawns": doubled, "isolated_pawns": isolated}})
    if not positions and focus == "sacrifices":
        checked = 0
        values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
        def balance(board, side):
            return sum(value * (len(board.pieces(piece, side)) - len(board.pieces(piece, not side))) for piece, value in values.items())
        for item in real_positions():
            if len(item["continuation"]) < 2: continue
            board = chess.Board(item["fen"])
            after = board.copy(stack=False)
            for uci in item["continuation"]: after.push_uci(uci)
            debt = balance(after, board.turn) - balance(board, board.turn)
            if debt >= 0: continue
            checked += 1
            move = chess.Move.from_uci(item["continuation"][0])
            feedback = engine_service.grade(board, move, time_ms=250)
            if feedback.get("classification") in ("Best", "Excellent", "Good") and feedback.get("confidence") in ("engine_estimate", "rechecked_estimate"):
                positions.append({**item, "topic": focus, "verified_move": move.uci(), "material_change": debt,
                    "verification": feedback, "difficulty": 3})
                break
            if checked >= 6: break
    # For tactical focuses, inspect authentic complete-game positions first,
    # then accept a motif only if a fresh engine comparison supports the move.
    # This bounded fallback helps new profiles without removing distracting pieces.
    if not positions and focus in ("forks", "pins", "skewers"):
        kind = {"forks": "fork", "pins": "pin", "skewers": "skewer"}[focus]
        checked = 0
        for item in real_positions():
            board = chess.Board(item["fen"])
            motif_moves = [move for move in board.legal_moves if objective_met(board, move, {"kind": kind})]
            for move in motif_moves:
                checked += 1
                feedback = engine_service.grade(board, move, time_ms=250)
                if feedback.get("classification") in ("Best", "Excellent", "Good") and feedback.get("confidence") in ("engine_estimate", "rechecked_estimate"):
                    positions.append({**item, "topic": focus, "verified_move": move.uci(), "difficulty": 2})
                    break
                if checked >= 6: break
            if positions or checked >= 6: break
    # Specific focused sessions must never label unrelated positions as that motif.
    if focus in ("mixed", "opening", "middlegame"):
        positions += [item for item in real_positions() if focus in ("mixed", item["topic"])]
    return positions


@router.post("/games", status_code=201)
def start_training_game(body: TrainingGameRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    state = db.get(PlayerLearningState, user.id)
    profile = state.data if state else {}
    focus = FOCUS_MAP.get(body.focus, body.focus)
    if focus == "personalized":
        recommendations = profile.get("recommendations", [])
        focus = recommendations[0].get("topic", "mixed") if recommendations else "mixed"
    positions = candidate_positions(db, user, focus)
    if not positions and body.focus == "personalized":
        focus, positions = "mixed", candidate_positions(db, user, "mixed")
    if not positions:
        raise HTTPException(422, "No verified realistic position for this focus yet. Analyze more games or choose mixed training.")
    history = db.scalars(select(LearningEvent).where(LearningEvent.user_id == user.id,
        LearningEvent.kind == "training_started").order_by(LearningEvent.created_at.desc()).limit(100)).all()
    repetitions = {}
    for event in history:
        key = position_key(event.fen)
        repetitions[key] = repetitions.get(key, 0) + 1
    attempts = db.scalars(select(LearningEvent).where(LearningEvent.user_id == user.id,
        LearningEvent.kind == "training_result", LearningEvent.topic == focus,
        LearningEvent.payload["initial_decision"].as_boolean().is_(True)).order_by(LearningEvent.created_at.desc()).limit(20)).all()
    # Count initial decisions in distinct unfamiliar positions, not every later
    # move in one session. Assisted solves and memorized repeats cannot raise it.
    unique = {}
    for item in reversed(attempts):
        if item.payload.get("initial_decision") and item.payload.get("verified"):
            unique[position_key(item.fen)] = item
    samples = list(unique.values())
    independent = [item for item in samples if item.payload.get("independent")]
    wins = sum(bool(item.payload.get("sound")) for item in independent)
    failures = sum(not item.payload.get("sound") for item in samples)
    target = 1 if len(samples) >= 6 and failures / len(samples) >= .6 else min(5, 2 + wins // 6)
    for item in positions:
        board = chess.Board(item["fen"])
        # An internal selection heuristic, not an Elo or proof of tactical depth.
        # Authentic boards are retained; later sessions select among their actual
        # branching factors and piece counts instead of removing distractions.
        item.setdefault("difficulty", min(5, 1 + int(len(board.piece_map()) >= 24)
            + int(board.legal_moves.count() >= 30) + int(board.fullmove_number >= 10)))
        item["complexity"] = {"pieces": len(board.piece_map()), "legal_moves": board.legal_moves.count()}
    selected = min(positions, key=lambda item: (repetitions.get(position_key(item["fen"]), 0),
        not item.get("mistake", False), abs(item.get("difficulty", 2) - target), -len(chess.Board(item["fen"]).piece_map())))
    board = chess.Board(selected["fen"])
    selected_key = position_key(board.fen())
    # Ranking is bounded, but lifetime exposure remains authoritative. A position
    # does not become unfamiliar merely because it fell outside the recent list.
    seen = db.scalar(select(func.count(LearningEvent.id)).where(LearningEvent.user_id == user.id,
        LearningEvent.kind == "training_started", func.substr(LearningEvent.fen, 1, len(selected_key)) == selected_key)) or 0
    view = create_game(GameCreate(mode="training", player_color="white" if board.turn else "black", fen=board.fen(), difficulty_mode="adaptive"), user, db)
    game = db.get(Game, view["id"])
    game.learning_source = "training"
    game.training_context = {"blind": body.blind, "minutes": body.minutes, **({"focus": body.focus if body.focus not in ("personalized", "mixed") else focus} if not body.blind else {})}
    db.add(GameEvent(game_id=game.id, revision=game.revision, kind="training_started", payload={**selected,
        "focus": focus, "blind": body.blind, "minutes": body.minutes, "training_difficulty": target, "repetition": seen}))
    db.add(LearningEvent(user_id=user.id, kind="training_started", topic=focus, fen=board.fen(),
        payload={"game_id": game.id, **selected, "blind": body.blind, "minutes": body.minutes}))
    db.commit()
    return {**view, "learning_source": "training", "training_context": game.training_context}
