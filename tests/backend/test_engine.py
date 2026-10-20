import chess
import pytest

from src.backend.engine import classify_move, engine_service, score_number


def candidate(cp=None, mate=None, uci="e2e4"):
    return {"uci": uci, "cp": cp, "mate": mate}


def test_classification_and_forced_and_shallow():
    assert classify_move(candidate(70), candidate(-250, uci="a2a3"), depth=15)["classification"] == "Blunder"
    assert classify_move(candidate(20), candidate(15, uci="d2d4"), depth=15)["classification"] == "Excellent"
    assert classify_move(candidate(20), candidate(-200), forced=True, depth=15)["classification"] == "Forced"
    assert classify_move(candidate(20), candidate(-200), depth=5)["classification"] == "Uncertain"


def test_mate_correct_sign_and_equivalent_mates():
    assert score_number(candidate(mate=3)) > score_number(candidate(2000))
    assert score_number(candidate(mate=-3)) < score_number(candidate(-2000))
    assert score_number(candidate(mate=0)) < 0
    assert classify_move(candidate(mate=2), candidate(mate=5), depth=15)["classification"] == "Excellent"
    assert classify_move(candidate(0), candidate(mate=-2), depth=15)["classification"] == "Blunder"


def test_real_multipv_and_correct_black_perspective():
    if not engine_service.path(): pytest.skip("Stockfish not installed")
    board = chess.Board()
    board.push_san("e4")
    evidence = engine_service.analyze(board, time_ms=120)
    assert len(evidence["candidates"]) == 3
    for move in evidence["candidates"]:
        assert chess.Move.from_uci(move["uci"]) in board.legal_moves
        assert move["white_cp"] == -move["cp"]
        variation = board.copy()
        for san in move["pv"]: variation.push_san(san)


def test_specific_candidate_starts_from_identical_root():
    if not engine_service.path(): pytest.skip("Stockfish not installed")
    board = chess.Board()
    evidence = engine_service.grade(board, board.parse_san("Nf3"), time_ms=100)
    assert evidence["fen"] == board.fen()
    assert evidence["played"]["uci"] == "g1f3"
    assert evidence["played"]["pv"][0] == "Nf3"
    assert board.fen() == chess.STARTING_FEN


def test_equivalent_decisively_winning_positions_are_not_blunders():
    assert classify_move(candidate(2000), candidate(1500, uci="d2d4"), depth=15)["classification"] == "Good"


def test_serious_grade_is_rechecked_and_unstable_search_is_not_a_confident_blunder(monkeypatch):
    from src.backend.engine import EngineService
    service = EngineService()
    board = chess.Board()
    calls = []
    def search(root, time_ms=250, candidates=3, root_moves=None, **kwargs):
        assert root.fen() == board.fen()
        calls.append((time_ms, bool(root_moves)))
        move = root_moves[0] if root_moves else root.parse_san("e4")
        value = 100 if not root_moves else -300 if time_ms == 100 else 90
        return {"fen": root.fen(), "candidates": [{"uci": move.uci(), "san": root.san(move), "cp": value,
                    "mate": None, "depth": 14, "pv": [root.san(move)], "pv_uci": [move.uci()]}]}
    monkeypatch.setattr(service, "analyze", search)
    feedback = service.grade(board, board.parse_san("a3"), time_ms=100)
    assert calls == [(100, False), (100, True), (600, False), (600, True)]
    assert feedback["rechecked"] and feedback["classification"] == "Uncertain"
    assert feedback["confidence"] == "unstable_search"


def test_deep_search_uses_separate_worker_and_preserves_requested_budget(monkeypatch):
    from src.backend.engine import EngineService
    service = EngineService()
    deep = EngineService(deep_worker=True)
    service._deep_service = deep
    received = []
    def analyze(board, **kwargs):
        received.append(kwargs)
        assert not service._lock.locked()
        return {"fen": board.fen()}
    monkeypatch.setattr(deep, "analyze", analyze)
    result = service.analyze(chess.Board(), time_ms=12000, mode="deep")
    assert received[0]["time_ms"] == 12000 and result["mode"] == "deep"


def test_practice_opponent_is_isolated_and_strongest_level_preserves_analysis(monkeypatch):
    import src.backend.engine as module
    from src.backend.engine import EngineService
    service = EngineService()
    calls = []
    practice_calls = []
    def analyze(board, **kwargs):
        calls.append(kwargs)
        return {"candidates": [{"uci": "e2e4"}, {"uci": "d2d4"}, {"uci": "g1f3"}]}
    monkeypatch.setattr(service, "analyze", analyze)
    def practice(board, difficulty, rng):
        practice_calls.append((difficulty, rng))
        return board.parse_san("Nc3")
    monkeypatch.setattr(service._opponent, "choose", practice)
    for difficulty in range(1, 5):
        assert service.play(chess.Board(), difficulty).uci() == "b1c3"
    assert practice_calls == [(level, module.random) for level in range(1, 5)]
    assert service.play(chess.Board(), 5).uci() == "e2e4"
    assert calls == [{"time_ms": 700, "candidates": 3}]
