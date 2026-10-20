"""Frozen teaching cases and a review gate that cannot pass on missing ratings."""
import copy

import chess
import pytest

from scripts.benchmark_coaching import (DIMENSIONS, LEVELS, load_positions, review_summary,
                                       legal_evidence, visual_failures, protected_hint_failures, validate_capture)
from src.backend.exercises import objective_met


def by_id():
    return {item["id"]: item for item in load_positions()}


def test_frozen_positions_cover_teaching_levels_and_legal_objectives():
    positions = load_positions()
    assert len(positions) == 40
    for item in positions:
        assert all(len(item["expected"][level]) > 70 for level in LEVELS)
        assert len(set(item["expected"].values())) == 3
        if "criterion" in item:
            board = chess.Board(item["fen"])
            assert objective_met(board, chess.Move.from_uci(item["move"]), item["criterion"])
    tags = {tag for item in positions for tag in item["tags"]}
    assert {"poisoned_capture", "underpromotion", "stalemate", "forced_mate", "castling", "en_passant", "ambiguity"} <= tags


def test_unrecapturable_capture_can_lose_to_verified_mate():
    item = by_id()["poisoned-pawn"]
    board = chess.Board(item["fen"])
    move = chess.Move.from_uci(item["move"])
    assert board.piece_type_at(move.to_square) == chess.PAWN
    board.push(move)
    assert not any(m.to_square == move.to_square and board.is_capture(m) for m in board.legal_moves)
    for value in item["line"][1:]: board.push_uci(value)
    assert board.is_checkmate() and board.turn == chess.BLACK


def test_special_rules_and_terminal_expectations_are_actual_board_facts():
    items = by_id()
    for key, predicate in [("stalemate", "is_stalemate"), ("checkmate", "is_checkmate")]:
        assert getattr(chess.Board(items[key]["fen"]), predicate)()
    board = chess.Board(items["underpromotion"]["fen"])
    queen, rook = board.copy(), board.copy()
    queen.push_uci("c7c8q")
    rook.push_uci("c7c8r")
    assert queen.is_stalemate() and not rook.is_game_over()
    assert chess.Move.from_uci("a7a6") in rook.legal_moves
    board = chess.Board(items["en-passant"]["fen"])
    assert board.is_en_passant(chess.Move.from_uci("e5d6"))
    board.push_uci("e5d6")
    assert board.piece_at(chess.D5) is None and board.piece_type_at(chess.D6) == chess.PAWN
    assert chess.Board(items["only-move"]["fen"]).legal_moves.count() == 1
    board = chess.Board(items["ambiguous-knights"]["fen"])
    assert {m.from_square for m in board.legal_moves if m.to_square == chess.E4} == {chess.D2, chess.F2}


def review_rows():
    return [{"id": "example", "level": level, "automatic_failures": [],
             "review": {"scores": dict.fromkeys(DIMENSIONS, 2), "hard_failure": False}}
            for level in LEVELS]


def test_teaching_gate_requires_reviews_at_every_level_and_no_hard_failures():
    assert review_summary(review_rows())["teaching_passed"]
    assert not review_summary([])["teaching_passed"]
    assert not review_summary(review_rows()[:1])["teaching_passed"]
    for modification in ("unreviewed", "hard_failure", "automatic_failure", "poor_teaching"):
        rows = copy.deepcopy(review_rows())
        if modification == "unreviewed": rows[0]["review"]["scores"] = {}
        if modification == "hard_failure": rows[0]["review"]["hard_failure"] = True
        if modification == "automatic_failure": rows[0]["automatic_failures"] = ["spoiler"]
        if modification == "poor_teaching": rows[0]["review"]["scores"] = dict.fromkeys(DIMENSIONS, 1)
        assert not review_summary(rows)["teaching_passed"], modification
    rows = review_rows()
    rows[0]["review"]["scores"]["accuracy"] = 3
    with pytest.raises(ValueError): review_summary(rows)
    with pytest.raises(ValueError): review_summary(rows + rows[:1])


def test_benchmark_checks_score_perspective_actual_overlays_and_hidden_hint_moves():
    board = chess.Board()
    root = board.fen()
    board.push_uci("e2e4")
    after = board.fen()
    analysis = {"fen": root, "perspective": "white", "candidates": [
        {"uci": "e2e4", "pv_uci": ["e2e4", "e7e5"]}]}
    assert not legal_evidence(analysis, root)
    assert legal_evidence({**analysis, "perspective": "black"}, root)
    assert legal_evidence({**analysis, "candidates": []}, root)
    visuals = {"insights": [{"fen": after, "claim_type": "board_geometry", "squares": ["d5"],
                             "arrows": [{"from": "e4", "to": "d5"}]}], "variations": [
        {"base_fen": root, "moves": ["e2e4"], "resulting_fen": after}]}
    assert not visual_failures(visuals, analysis, root)
    visuals["insights"][0]["arrows"] = [{"from": "e4", "to": "e8"}]
    assert "Unsupported visual arrow" in visual_failures(visuals, analysis, root)
    visuals["insights"][0]["fen"] = chess.Board("7k/8/8/8/8/8/8/K7 w - - 0 1").fen()
    assert "Visual insight belongs to an unsupported position" in visual_failures(visuals, analysis, root)
    hints = [{"fen": root, "level": level, "text": "Look for forcing moves."} for level in (1, 2)]
    assert not protected_hint_failures(hints, root)
    hints[0]["insights"] = [{"arrows": [{"from": "e2", "to": "e4"}]}]
    assert protected_hint_failures(hints, root)


def test_final_review_rejects_changed_positions_and_rechecks_deleted_failure_labels():
    positions = load_positions()
    rows = [{"id": item["id"], "level": level, "fen": item["fen"], "question": item["question"],
             "expected": item["expected"][level], "actual": "An explanation.", "automatic_failures": [],
             "review": {"scores": dict.fromkeys(DIMENSIONS, 2), "hard_failure": False}}
            for item in positions for level in LEVELS]
    report = {"benchmark_version": 1, "rows": rows}
    checked = validate_capture(report)
    assert not review_summary(checked)["teaching_passed"]  # Missing captured evidence is not a pass.
    rows[0]["fen"] = chess.STARTING_FEN
    with pytest.raises(ValueError, match="frozen position"):
        validate_capture(report)


def test_curriculum_rechecks_never_shorten_the_requested_search_or_flip_black_scores():
    import chess.engine
    from scripts.validate_exercises import compare_decision
    class ComparisonEngine:
        def __init__(self): self.budgets = []
        def analyse(self, board, limit, **kwargs):
            self.budgets.append(limit.time)
            # White-relative scores: with Black to move, the chosen move is worse by 180cp.
            score = 150 if kwargs.get("root_moves") else -30
            return {"depth": 12, "score": chess.engine.PovScore(chess.engine.Cp(score), chess.WHITE)}
    engine = ComparisonEngine()
    board = chess.Board()
    board.push_san("e4")
    with pytest.raises(ValueError, match="Unsound"):
        compare_decision(board, board.parse_san("e5"), engine, 10)
    assert len(engine.budgets) == 4
    assert min(engine.budgets[2:]) >= max(engine.budgets[:2])
