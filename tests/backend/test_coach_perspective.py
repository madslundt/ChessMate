"""A paused computer turn must not silently change the learner's identity."""
import chess
import pytest

from src.backend.chess_tools import observations
from src.backend.coach_facts import build_statements
from src.backend.schemas import Preferences


def facts(board, color="white", language="en", candidates=None, mode="training"):
    context = {"analysis": {"fen": board.fen(), "candidates": candidates or [], "observations": observations(board)},
               "game": {"player_color": color, "mode": mode}, "requested_candidates": [],
               "question": "Show the best candidate variation", "preferences": Preferences(show_pv=True).model_dump()}
    return build_statements(board, context, language, True)


@pytest.mark.parametrize("language", ["en", "da"])
def test_after_e4_center_is_still_whites_while_computer_is_paused(language):
    board = chess.Board()
    board.push_san("e4")
    statements = facts(board, language=language)
    assert "d5" in statements["center"]
    assert "Black" in statements["turn"] if language == "en" else "Sort" in statements["turn"]
    assert board.turn == chess.BLACK  # Never manufacture a White-to-move position.


@pytest.mark.parametrize("language,piece_word", [("en", "Your bishop on c4"), ("da", "Din løber på c4")])
def test_exposed_piece_belongs_to_learner_even_on_opponents_turn(language, piece_word):
    board = chess.Board("7k/8/3n4/8/2B5/8/8/4K3 b - - 0 1")
    assert board.is_valid()
    statements = facts(board, language=language)
    assert piece_word in statements["exposed_0"]
    assert "d6" in statements["attackers_0"]
    assert "no_exposed" not in statements
    assert "after Black" in statements["question"] if language == "en" else "Sort har svaret" in statements["question"]


def test_defenders_are_learners_pieces_not_side_to_moves():
    board = chess.Board("7k/8/3n4/8/2B5/8/1N6/4K3 b - - 0 1")
    statements = facts(board)
    assert "c4" in statements["defended_attack"] and "b2" in statements["defended_attack"]
    assert "no_exposed" in statements


@pytest.mark.parametrize("fen,learner,root_en,root_da", [
    ("4k3/8/8/8/8/8/4R3/4K3 b - - 0 1", "white", "Black", "Sort"),
    ("4k3/4r3/8/8/8/8/8/4K3 w - - 0 1", "black", "White", "Hvid"),
])
@pytest.mark.parametrize("language", ["en", "da"])
def test_opponents_check_and_castling_use_named_side(fen, learner, root_en, root_da, language):
    board = chess.Board(fen)
    assert board.is_valid() and board.is_check()
    statements = facts(board, learner, language)
    root = root_da if language == "da" else root_en
    assert statements["check"].startswith(root)
    assert root in statements["question"]
    assert "You are in check" not in statements["check"] and "Du står i skak" not in statements["check"]
    assert "reassess" in statements["castle"] if language == "en" else "vurder" in statements["castle"]


@pytest.mark.parametrize("language,root", [("en", "Black"), ("da", "Sort")])
def test_opponents_castling_candidate_is_explicitly_named(language, root):
    board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1")
    candidate = {"uci": "e8g8", "san": "O-O", "cp": 0, "mate": None, "pv_uci": ["e8g8"]}
    statements = facts(board, language=language, candidates=[candidate])
    assert statements["candidate_0"].startswith(f"For {root}: O-O")
    assert "your king" not in statements["candidate_0"] and "giver dig" not in statements["candidate_0"]
    assert "reassess White" in statements["castle"] if language == "en" else "vurder Hvid" in statements["castle"]


@pytest.mark.parametrize("language", ["en", "da"])
def test_material_change_uses_learner_pov_when_opponent_captures(language):
    board = chess.Board("k2r4/8/8/8/8/8/8/3QK3 b - - 0 1")
    candidate = {"uci": "d8d1", "san": "Rxd1+", "cp": 900, "mate": None, "pv_uci": ["d8d1"]}
    statements = facts(board, language=language, candidates=[candidate])
    assert "-9" in statements["consequence_0"]
    assert "+9" not in statements["consequence_0"]


def test_analysis_board_uses_actual_root_side_without_assigned_learner():
    board = chess.Board()
    board.push_san("e4")
    statements = facts(board, "white", mode="analysis")
    assert "turn" not in statements  # An analysis board has no fixed player's turn.
    assert "reassess White" not in statements["castle"]


@pytest.mark.parametrize("language,side", [("en", "Black to move"), ("da", "Sort i trækket")])
def test_generic_hints_name_root_side_without_assigning_it_to_user(language, side):
    from src.backend.coach import CoachService
    board = chess.Board()
    board.push_san("e4")
    hint = CoachService().hint(board, 3, language, time_ms=50)
    assert hint["text"].startswith(side)
    assert hint["perspective"] == "black"
    assert "your" not in hint["text"] and "din " not in hint["text"]
