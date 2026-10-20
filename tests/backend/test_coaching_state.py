import json

import chess

from src.backend.chess_tools import observations
from src.backend.coaching_state import advance_discovery, public_state
from src.backend.schemas import Preferences


FEN = "4k3/8/8/8/4r3/8/4B3/6K1 w - - 0 1"


def context(question, candidates=None):
    board = chess.Board(FEN)
    return board, {"question": question, "preferences": Preferences(coaching_mode="socratic").model_dump(),
        "learner_color": "white", "analysis": {"observations": observations(board), "candidates": []},
        "requested_candidates": candidates or []}


def test_discoveries_progress_only_with_verified_piece_and_attacker_references():
    board, ctx = context("Is my bishop on e2 vulnerable?")
    first = advance_discovery(board, ctx, None)
    assert first["stage"] == "identify" and "exposed:e2" in first["discovered_ids"]
    board, ctx = context("The attacker is on e5")
    wrong = advance_discovery(board, ctx, first)
    assert wrong["stage"] == "identify" and "attacker:e2:e5" not in wrong["discovered_ids"]
    board, ctx = context("The rook on e4")
    correct = advance_discovery(board, ctx, wrong)
    assert correct["stage"] == "calculate" and "attacker:e2:e4" in correct["discovered_ids"]


def test_repeated_help_is_progressive_without_revealing_an_engine_move():
    board, ctx = context("I don't know, help")
    first = advance_discovery(board, ctx, None)
    second = advance_discovery(board, ctx, first)
    assert first["question"] != second["question"] and second["help_level"] == 2
    assert "e2" in second["question"] and not second["discovered_ids"]


def test_calculation_prediction_and_outcome_are_checked_before_reflection():
    candidate = {"uci": "e2f3", "pv_uci": ["e2f3", "e4f4", "f3g2"]}
    board, ctx = context("What if Bf3?", [candidate])
    chosen = advance_discovery(board, ctx, None)
    board, ctx = context("Rf4")
    predicted = advance_discovery(board, ctx, chosen)
    assert predicted["stage"] == "evaluate" and "reply:e4f4" in predicted["discovered_ids"]
    board, ctx = context("I win")
    wrong = advance_discovery(board, ctx, predicted)
    assert wrong["stage"] == "evaluate" and "does not prove a win" in wrong["acknowledgement"]
    board, ctx = context("Material change +0")
    right = advance_discovery(board, ctx, wrong)
    assert right["stage"] == "reflect" and "evaluated:e2f3" in right["discovered_ids"]
    assert "expected_reply_uci" not in public_state(chosen) and "line_outcome" not in public_state(chosen)


def test_chat_reload_restores_exact_visual_evidence_source_and_guided_state(signed):
    game = signed.post("/api/games", json={"fen": FEN}).json()
    request = {"fen": FEN, "game_id": game["id"], "revision": 0,
               "question": "Is my bishop on e2 vulnerable?", "teaching_mode": "guided"}
    response = signed.post("/api/coach", json=request)
    done = next(json.loads(frame.split("data: ", 1)[1]) for frame in response.text.split("\n\n") if frame.startswith("event: done"))
    reloaded = signed.get(f"/api/games/{game['id']}/conversation").json()
    answer = reloaded["messages"][-1]
    for key in ("source", "fallback_reason", "insights", "variations", "evidence_ids", "state"):
        assert answer[key] == done[key]
    assert reloaded["state"]["stage"] == "identify" and "exposed:e2" in reloaded["state"]["discovered_ids"]
    direct = signed.post("/api/coach", json={**request, "question": "Explain directly", "teaching_mode": "direct"})
    assert '"mode": "direct"' in direct.text
    assert signed.get(f"/api/games/{game['id']}/conversation").json()["state"]["mode"] == "direct"
