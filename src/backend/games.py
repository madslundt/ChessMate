"""Revision-guarded authoritative game state and immutable move evidence."""
import io

import chess
import chess.pgn
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.exc import OperationalError

from .auth import current_user
from .chess_tools import parse_board, parse_move
from .database import get_db
from .engine import EngineUnavailable, engine_service
from .models import CoachingMessage, Game, GameEvent, User
from .schemas import GameCreate, MoveRequest, Preferences, Revision
from .views import GameView

router = APIRouter(prefix="/games", tags=["Games"])


def board_for(game: Game) -> chess.Board:
    return parse_board(game.initial_fen, [m["uci"] for m in game.moves])


def owned_game(db: Session, game_id: str, user: User, revision: int | None = None) -> Game:
    query = select(Game).where(Game.id == game_id, Game.user_id == user.id)
    if revision is not None: query = query.with_for_update()
    game = db.scalar(query)
    if not game: raise HTTPException(404, "Game not found")
    if revision is not None and game.revision != revision:
        raise HTTPException(409, "This game changed. Refresh before trying again.")
    return game


def filtered_evidence(value, hidden: set[str]):
    if isinstance(value, dict): return {key: filtered_evidence(item, hidden) for key, item in value.items() if key not in hidden}
    if isinstance(value, list): return [filtered_evidence(item, hidden) for item in value]
    return value


def state(game: Game, user: User | None = None, include_evidence: bool = False) -> dict:
    board = board_for(game)
    outcome = board.outcome(claim_draw=True)
    prefs = Preferences.model_validate(user.preferences or {}) if user else Preferences()
    moves = []
    for original in game.moves:
        move = {**original}
        feedback = original.get("feedback")
        if feedback and not include_evidence:
            if prefs.feedback == "none" or ((prefs.feedback == "mistakes" or prefs.feedback_frequency == "mistakes")
                    and feedback.get("classification") not in ("Inaccuracy", "Mistake", "Blunder")):
                feedback = None
            else:
                hidden = set()
                if not prefs.show_alternatives or prefs.hide_best_moves: hidden.update(("best", "alternatives"))
                if prefs.feedback != "detailed": hidden.add("takeaway")
                if not prefs.show_pv:
                    hidden.update(("pv", "pv_uci", "reply", "legal_reply_captures", "legal_captures", "legal_checks", "verified_short_forks"))
                if not prefs.show_evaluation:
                    hidden.update(("cp", "mate", "white_cp", "white_mate", "difference_cp", "loss_cp", "win_chance_loss"))
                feedback = filtered_evidence(feedback, hidden)
            move["feedback"] = feedback
        moves.append(move)
    return {"id": game.id, "fen": board.fen(), "initial_fen": game.initial_fen, "moves": moves,
            "revision": game.revision, "mode": game.mode, "player_color": game.player_color,
            "difficulty": game.difficulty, "created_at": game.created_at.isoformat(),
            "status": outcome.termination.name.lower() if outcome else "check" if board.is_check() else "playing",
            "result": outcome.result() if outcome else "*", "turn": "white" if board.turn else "black",
            "legal_moves": [m.uci() for m in board.legal_moves], "check": board.is_check()}


def append_move(game: Game, board: chess.Board, move: chess.Move, feedback: dict | None, source: str) -> dict:
    record = {"uci": move.uci(), "san": board.san(move), "before_fen": board.fen(),
              "color": "white" if board.turn else "black", "source": source, "feedback": feedback}
    board.push(move)
    record["fen"] = board.fen()
    game.moves = [*game.moves, record]
    return record


def commit_event(db: Session, game: Game, kind: str, payload: dict) -> None:
    game.revision += 1
    db.add(GameEvent(game_id=game.id, revision=game.revision, kind=kind, payload=payload))
    try: db.commit()
    except (StaleDataError, OperationalError):
        db.rollback()
        raise HTTPException(409, "This game changed. Refresh before trying again.") from None


@router.post("", status_code=201, response_model=GameView)
def create_game(data: GameCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if data.fen and data.pgn: raise HTTPException(422, "Import either FEN or PGN, not both")
    records = []
    try:
        board = parse_board(data.fen or chess.STARTING_FEN)
        initial_fen = board.fen()
        if data.pgn:
            imported = chess.pgn.read_game(io.StringIO(data.pgn))
            if imported is None or imported.errors: raise ValueError("PGN contains invalid moves")
            board = imported.board()
            if not board.is_valid(): raise ValueError("Invalid PGN starting position")
            initial_fen = board.fen()
            for index, move in enumerate(imported.mainline_moves()):
                if index >= 2000: raise ValueError("PGN exceeds 2000 plies")
                if move not in board.legal_moves: raise ValueError("Illegal move in PGN")
                record = {"uci": move.uci(), "san": board.san(move), "before_fen": board.fen(),
                          "color": "white" if board.turn else "black", "source": "import", "feedback": None}
                board.push(move)
                record["fen"] = board.fen()
                records.append(record)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    game = Game(user_id=user.id, initial_fen=initial_fen, moves=records, mode=data.mode,
                player_color=data.player_color, difficulty=data.difficulty)
    db.add(game)
    db.flush()
    db.add(GameEvent(game_id=game.id, revision=0, kind="created", payload={"initial_fen": initial_fen, "moves": records, "mode": data.mode, "player_color": data.player_color, "difficulty": data.difficulty}))
    db.commit()
    return state(game, user)


@router.get("", response_model=list[GameView])
def list_games(user: User = Depends(current_user), db: Session = Depends(get_db), limit: int = 50) -> list[dict]:
    games = db.scalars(select(Game).where(Game.user_id == user.id).order_by(Game.created_at.desc()).limit(max(1, min(100, limit))))
    return [state(game, user) for game in games]


@router.get("/{game_id}", response_model=GameView)
def get_game(game_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return state(owned_game(db, game_id, user), user)


@router.post("/{game_id}/moves", response_model=GameView)
def make_move(game_id: str, data: MoveRequest, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    game = owned_game(db, game_id, user, data.revision)
    board = board_for(game)
    if board.is_game_over(claim_draw=True): raise HTTPException(409, "Game has ended")
    if game.mode != "analysis" and board.turn != (game.player_color == "white"):
        raise HTTPException(409, "It is the computer's turn")
    try: move = parse_move(board, data.move)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    prefs = Preferences.model_validate(user.preferences or {})
    try: feedback = engine_service.grade(board, move, time_ms=prefs.analysis_time_ms, language=prefs.coach_language)
    except EngineUnavailable:
        feedback = {"classification": "Uncertain", "text": "Motoren er utilgængelig; trækket er gemt uden en motorvurdering." if prefs.coach_language == "da" else "Engine unavailable; move saved without an engine grade.",
                    "fen": board.fen(), "move": move.uci(), "confidence": "unavailable"}
    record = append_move(game, board, move, feedback, "player")
    commit_event(db, game, "move", record)
    return state(game, user)


@router.post("/{game_id}/computer", response_model=GameView)
def computer_move(game_id: str, data: Revision, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    game = owned_game(db, game_id, user, data.revision)
    board = board_for(game)
    if game.mode == "analysis": raise HTTPException(409, "Analysis games have no automatic opponent")
    if board.is_game_over(claim_draw=True): raise HTTPException(409, "Game has ended")
    if board.turn == (game.player_color == "white"): raise HTTPException(409, "It is the player's turn")
    try: move = engine_service.play(board, game.difficulty)
    except EngineUnavailable as exc: raise HTTPException(503, str(exc)) from exc
    record = append_move(game, board, move, None, "computer")
    commit_event(db, game, "computer_move", record)
    return state(game, user)


@router.post("/{game_id}/undo", response_model=GameView)
def undo(game_id: str, data: Revision, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    game = owned_game(db, game_id, user, data.revision)
    if game.mode not in ("training", "analysis"): raise HTTPException(409, "Undo is available in training and analysis games")
    if not game.moves: raise HTTPException(409, "No moves to undo")
    count = 1
    if game.mode == "training" and game.moves[-1]["source"] == "computer" and len(game.moves) >= 2: count = 2
    removed = game.moves[-count:]
    game.moves = game.moves[:-count]
    commit_event(db, game, "undo", {"removed": removed})
    return state(game, user)


@router.get("/{game_id}/pgn", response_class=PlainTextResponse)
def export_pgn(game_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> str:
    game = owned_game(db, game_id, user)
    board = board_for(game)
    exported = chess.pgn.Game.from_board(board)
    exported.headers["Event"] = "Chessmate training"
    exported.headers["White"] = user.name if game.player_color == "white" else "Computer"
    exported.headers["Black"] = user.name if game.player_color == "black" else "Computer"
    return str(exported)


@router.get("/{game_id}/review")
@router.post("/{game_id}/review")
def review(game_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    game = owned_game(db, game_id, user)
    mistakes, positives = [], []
    for index, record in enumerate(game.moves):
        feedback = record.get("feedback") or {}
        item = {"ply": index + 1, "san": record["san"], "fen": record["before_fen"], "feedback": feedback}
        if feedback.get("classification") in ("Mistake", "Blunder", "Inaccuracy"): mistakes.append(item)
        if feedback.get("classification") in ("Best", "Excellent"): positives.append(item)
    topics = []
    for item in mistakes:
        facts = item["feedback"].get("facts", {})
        topic = "opening" if facts.get("develops_minor") else "endgame" if len(chess.Board(item["fen"]).piece_map()) <= 10 else "middlegame"
        topics.append(topic)
    count = sum(bool(m.get("feedback")) for m in game.moves)
    da = Preferences.model_validate(user.preferences or {}).coach_language == "da"
    return {"game_id": game.id, "revision": game.revision,
            "summary": f"Gennemgået {count} spillerbeslutninger. Fokusér på de mest lærerige stillinger nedenfor." if da else f"Reviewed {count} player decisions. Focus on the most instructive positions below.",
            "positives": positives[:3], "mistakes": sorted(mistakes, key=lambda i: i["feedback"].get("loss_cp", 0), reverse=True)[:5],
            "topics": list(dict.fromkeys(topics))[:2], "result": board_for(game).result(claim_draw=True),
            "limitations": "Estimater fra korte søgninger; taktiske mønstre angives kun efter selvstændig verifikation." if da else "Short-search estimates; tactical motifs are included only when independently verified."}


@router.get("/{game_id}/conversation")
def conversation(game_id: str, fen: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    game = owned_game(db, game_id, user)
    target = fen or board_for(game).fen()
    try: target = parse_board(target).fen()
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    messages = db.scalars(select(CoachingMessage).where(CoachingMessage.user_id == user.id,
        CoachingMessage.game_id == game.id, CoachingMessage.fen == target)
        .order_by(CoachingMessage.created_at.desc()).limit(50)).all()
    return {"game_id": game.id, "fen": target, "revision": game.revision,
            "messages": [{"id": m.id, "role": m.role, "content": m.content, "fen": m.fen,
                          "created_at": m.created_at.isoformat()} for m in reversed(messages)]}
