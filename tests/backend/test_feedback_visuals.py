import copy
from datetime import datetime, timezone

import chess
import pytest

from src.backend.games import state
from src.backend.models import Game, User


def saved_game(black=False):
    root = chess.Board()
    root.push_san("e4")
    root.push_san("d5")
    if black:
        root = root.mirror()
    move = root.parse_san("a6" if black else "a3")
    best = root.parse_san("exd4" if black else "exd5")
    after = root.copy()
    after.push(move)
    reply = after.parse_san("dxe5" if black else "dxe4")
    feedback = {"classification": "Blunder", "fen": root.fen(), "move": move.uci(),
        "text": "A bad move.", "best": {"uci": best.uci(), "san": root.san(best), "cp": 50},
        "played": {"uci": move.uci(), "pv_uci": [move.uci(), reply.uci()], "cp": -250}}
    game = Game(id="saved", user_id="owner", mode="training", player_color="white", difficulty=2,
        initial_fen=root.fen(), revision=1, created_at=datetime.now(timezone.utc), moves=[{
            "uci": move.uci(), "san": root.san(move), "before_fen": root.fen(), "fen": after.fen(),
            "color": "black" if black else "white", "feedback": feedback}])
    return game, root, best


@pytest.mark.parametrize("language", ["en", "da"])
def test_saved_feedback_gets_minimal_past_improvement_and_clickable_threats_without_full_spoilers(language):
    game, root, best = saved_game()
    original = copy.deepcopy(game.moves)
    user = User(preferences={"hide_best_moves": True, "show_alternatives": False, "show_pv": False,
                             "show_evaluation": False, "coach_language": language})
    feedback = state(game, user)["moves"][0]["feedback"]
    assert feedback["improvement"] == {"uci": best.uci(), "san": root.san(best), "fen": root.fen()}
    assert "best" not in feedback and "alternatives" not in feedback
    assert "cp" not in feedback["played"] and "pv_uci" not in feedback["played"]
    assert feedback["threats"][0]["fen"] == game.moves[0]["fen"]
    assert ("pawn" if language == "en" else "bonde") in feedback["threats"][0]["label"]
    assert game.moves == original


def test_opponents_past_improvement_is_available_without_revealing_learners_next_reply():
    game, root, best = saved_game(black=True)
    feedback = state(game, User(preferences={"hide_best_moves": True}))["moves"][0]["feedback"]
    assert feedback["improvement"] == {"uci": best.uci(), "san": root.san(best), "fen": root.fen()}
    assert feedback["threats"] == []
    revealed = state(game, User(preferences={"hide_best_moves": False}))["moves"][0]["feedback"]
    assert revealed["threats"][0]["label"].startswith("dxe5")


def test_stale_or_illegal_improvement_evidence_is_not_presented_as_verified():
    game, root, best = saved_game()
    feedback = game.moves[0]["feedback"]
    feedback["best"]["uci"] = "e2e5"
    assert "improvement" not in state(game)["moves"][0]["feedback"]
    feedback["fen"] = chess.STARTING_FEN
    feedback["improvement"] = {"uci": best.uci(), "san": root.san(best), "fen": root.fen()}
    feedback["threats"] = [{"id": "stale", "fen": root.fen()}]
    visible = state(game)["moves"][0]["feedback"]
    assert "improvement" not in visible and not visible.get("threats")


def test_feedback_visibility_setting_still_hides_entire_feedback():
    game, _, _ = saved_game()
    assert state(game, User(preferences={"feedback": "none"}))["moves"][0]["feedback"] is None
