import chess

from src.backend.coaching_strategy import candidate_strategy, strategic_facts, strategic_insights


def test_pawn_structure_distinguishes_facts_from_backward_pawn_heuristic():
    board = chess.Board("6k1/8/2p5/2P1P3/3P4/8/7P/6K1 w - - 0 1")
    facts = strategic_facts(board)
    side = facts["sides"]["white"]
    assert "d4" in side["backward_candidates"] and "h2" in side["isolated"]
    assert "e5" in side["passed"] and "c5" not in side["passed"]
    assert "a" in facts["open_files"] and "c" not in facts["open_files"]
    insights = strategic_insights(board, chess.WHITE, "advanced")
    backward = next(item for item in insights if item["id"] == "strategy_backward")
    assert backward["claim_type"] == "strategic_interpretation" and "not proof" in backward["text"]


def test_outpost_candidates_require_pawn_support_and_no_straight_pawn_challenge():
    board = chess.Board("6k1/8/7p/3N4/2P5/8/8/6K1 w - - 0 1")
    assert strategic_facts(board)["sides"]["white"]["outpost_candidates"] == ["d5"]
    board.set_piece_at(chess.C7, chess.Piece(chess.PAWN, chess.BLACK))
    assert not strategic_facts(board)["sides"]["white"]["outpost_candidates"]


def test_supported_piece_is_explained_even_outside_outpost_rank():
    board = chess.Board("6k1/8/8/8/8/1P2N3/8/6K1 w - - 0 1")
    strategy = candidate_strategy(board, {"uci": "e3c4", "pv_uci": ["e3c4"]})
    support = next(effect for effect in strategy["effects"] if effect["id"].endswith("pawn_support"))
    assert "b3" in support["text"] and "c4" in support["text"]
    assert "does not by itself prove safety" in support["text"]
    assert not any(effect["id"].endswith("_outpost") for effect in strategy["effects"])


def test_line_end_queenless_observation_uses_exact_resulting_fen():
    board = chess.Board("r2q2k1/8/8/8/8/8/8/3Q2K1 w - - 0 1")
    strategy = candidate_strategy(board, {"uci": "d1d8", "pv_uci": ["d1d8", "a8d8"]})
    effect = next(effect for effect in strategy["effects"] if effect["id"].endswith("queen_exchange"))
    replay = board.copy()
    replay.push_uci("d1d8")
    replay.push_uci("a8d8")
    assert effect["fen"] == replay.fen()
    assert "Both queens are off the board" in effect["text"] and "exchanges both queens" not in effect["text"]


def test_skill_defaults_apply_on_explicit_level_change_without_disabling_spoilers(signed):
    advanced = signed.patch("/api/settings", json={"complexity": "advanced"}).json()
    assert advanced["max_explanation_length"] == 300 and advanced["feedback"] == "detailed"
    assert advanced["show_pv"] and advanced["hide_best_moves"]
    custom = signed.patch("/api/settings", json={"skill_defaults": False, "max_explanation_length": 75}).json()
    assert custom["max_explanation_length"] == 75
    intermediate = signed.patch("/api/settings", json={"complexity": "intermediate"}).json()
    assert intermediate["max_explanation_length"] == 75 and not intermediate["skill_defaults"]
    reset = signed.patch("/api/settings", json={"skill_defaults": True}).json()
    assert reset["max_explanation_length"] == 180 and reset["show_pv"]
