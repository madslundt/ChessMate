"""Append-only disclosures tied to actual game positions, including undo/retry visits."""
import chess
from fastapi import HTTPException
from sqlalchemy import select

from .learning_evidence import position_key
from .learning_models import LearningEvent
from .models import Game

CATEGORIES = ("independent", "general_guidance", "piece_revealed", "destination_revealed", "full_solution", "engine_assisted")


def record_assistance(db, user, game_id, fen, category, source, suggested_move=None, revealed=None, revision=None):
    """Do not commit: disclosure and its originating response should save together."""
    if category not in CATEGORIES[1:]: raise HTTPException(422, "Unknown assistance category")
    try: board = chess.Board(fen)
    except ValueError: raise HTTPException(422, "Invalid assistance position") from None
    if not board.is_valid(): raise HTTPException(422, "Invalid assistance position")
    if not game_id: return None
    game = db.scalar(select(Game).where(Game.id == game_id, Game.user_id == user.id))
    if not game: raise HTTPException(404, "Game not found")
    if revision is not None and game.revision != revision:
        raise HTTPException(409, "The game changed; refresh the assistance context")
    positions = [game.initial_fen, *(record["fen"] for record in game.moves)]
    matches = [index for index, position in enumerate(positions) if position_key(position) == position_key(fen)]
    if not matches: return None  # A hypothetical analysis position is not a live decision.
    if suggested_move:
        try: move = chess.Move.from_uci(suggested_move)
        except ValueError: raise HTTPException(422, "Invalid suggested move") from None
        if move not in board.legal_moves: raise HTTPException(422, "Suggested move is illegal")
    event = LearningEvent(user_id=user.id, kind="assistance", topic="decision", fen=board.fen(), payload={
        "game_id": game.id, "revision": game.revision, "ply": max(matches), "category": category,
        "source": source[:80], "suggested_move": suggested_move, "revealed": revealed or {},
        "position_key": position_key(fen)})
    db.add(event)
    return event


def decision_assistance(db, game, fen, played_move):
    events = db.scalars(select(LearningEvent).where(LearningEvent.user_id == game.user_id,
        LearningEvent.kind == "assistance", LearningEvent.fen == fen).order_by(LearningEvent.created_at)).all()
    events = [event for event in events if event.payload.get("game_id") == game.id]
    category = max((event.payload["category"] for event in events), key=CATEGORIES.index, default=(
        "independent" if game.assistance_tracked and game.learning_source != "import" else "unknown"))
    return {"category": category, "event_ids": [event.id for event in events],
            "followed_suggestion": any(event.payload.get("suggested_move") == played_move for event in events),
            "tracked": bool(game.assistance_tracked)}
