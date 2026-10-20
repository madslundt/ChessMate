"""Observable learning concepts. Geometry identifies practice themes, never a forced result."""
import chess
from datetime import timezone

from .chess_tools import move_facts
from .exercises import objective_met

SKILL_LABELS = {
    "forcing_moves": ("Checks, captures and threats", "Skakker, slag og trusler"),
    "defense": ("Defensive resources", "Forsvarsressourcer"),
    "safety": ("Piece and king safety", "Brik- og kongesikkerhed"),
    "calculation_response": ("Predicting the opponent’s response", "Forudsig modstanderens svar"),
    "exchanges": ("Exchanges and recaptures", "Afbytninger og genslag"),
    "plans": ("Position-specific plans", "Stillingsbestemte planer"),
    "endgames": ("Endgame decisions", "Slutspilsbeslutninger"),
}


def utc_iso(value) -> str:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def position_key(fen: str) -> str:
    """Counters do not change a move's geometry; keep side, castling and en-passant rights."""
    return " ".join(chess.Board(fen).fen().split()[:4])


def topic_for(board: chess.Board, move: chess.Move | None = None) -> str:
    if move is not None:
        for topic, kind in (("forks", "fork"), ("pins", "pin"), ("skewers", "skewer")):
            if objective_met(board, move, {"kind": kind}): return topic
    return "endgame" if len(board.piece_map()) <= 10 else "opening" if board.fullmove_number <= 10 else "middlegame"


def observed_skills(board: chess.Board, move: chess.Move, feedback: dict | None = None,
                    criterion: dict | None = None) -> list[str]:
    """Attach a concept only when a legal move or explicit verified exercise supports it."""
    if move not in board.legal_moves: return []
    facts, skills = move_facts(board, move), set()
    kind = (criterion or {}).get("kind")
    if board.gives_check(move) or board.is_capture(move) or move.promotion:
        skills.add("forcing_moves")
    if board.is_check() or kind in ("defend", "unpin", "hold_corner", "prevent_mate", "escape_check"):
        skills.add("defense")
    after = board.copy(stack=False)
    after.push(move)
    if board.is_attacked_by(not board.turn, move.from_square) and not after.is_attacked_by(not board.turn, move.to_square):
        skills.add("defense")
    if any(board.is_attacked_by(not board.turn, chess.parse_square(item["square"]))
           for item in facts.get("added_geometric_support", [])):
        skills.add("defense")
    played = (feedback or {}).get("played") or {}
    if board.is_check() or facts.get("newly_exposed_own") or board.is_castling(move) or played.get("mate", 1) is not None and played.get("mate", 1) <= 0:
        skills.add("safety")
    if board.is_capture(move) and facts.get("legal_reply_captures") or kind == "simplify":
        skills.add("exchanges")
    if kind in ("outpost", "rook_seventh", "repair_pawns", "pawn_challenge", "center", "develop", "fresh_development", "finish_development"):
        skills.add("plans")
    if len(board.piece_map()) <= 10: skills.add("endgames")
    return sorted(skills)


def grade_is_usable(feedback: dict) -> bool:
    return (feedback.get("classification") in ("Best", "Excellent", "Good", "Forced", "Inaccuracy", "Mistake", "Blunder")
            and feedback.get("confidence") in ("engine_estimate", "rechecked_estimate", "forced")
            and bool(feedback.get("best")) and bool(feedback.get("played"))
            and (feedback.get("confidence") == "forced" or min(feedback["best"].get("depth", 0), feedback["played"].get("depth", 0)) >= 8))
