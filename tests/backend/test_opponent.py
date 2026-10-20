from random import Random

import chess
import chess.engine
import pytest

from src.backend.engine import EngineService, EngineUnavailable
from src.backend.opponent import (OpponentService, OpponentUnavailable, PROFILES,
                                  allows_mate_in_one, candidate_loss, choose_candidate)


def evidence(cp=None, mate=None, uci="e2e4", **kwargs):
    return {"uci": uci, "cp": cp, "mate": mate, "allows_mate_in_one": False, **kwargs}


def test_fixed_candidate_error_profiles_get_progressively_stronger():
    candidates = [evidence(cp, uci=str(cp)) for cp in (100, 90, 40, -50, -150, -350, -550, -1000)]
    means, errors = [], []
    for level in range(1, 5):
        rng = Random(713)
        losses = [candidate_loss(candidates[0], choose_candidate(candidates, level, rng)) for _ in range(6000)]
        means.append(sum(losses) / len(losses))
        errors.append(sum(loss > 120 for loss in losses) / len(losses))
        assert max(losses) <= 700
    assert means == sorted(means, reverse=True)
    assert all(left > right for left, right in zip(means, means[1:]))
    assert .55 < errors[0] < .65 and .28 < errors[1] < .36
    assert errors[0] > errors[1] > errors[2] > errors[3]


def test_mate_policy_retains_sign_and_never_rejects_a_longer_forced_win():
    assert candidate_loss(evidence(mate=2), evidence(mate=8)) == 0
    assert candidate_loss(evidence(mate=2), evidence(cp=0)) == 400
    assert candidate_loss(evidence(cp=0), evidence(mate=-3)) == 600
    assert candidate_loss(evidence(mate=-8), evidence(mate=-2)) == 60
    assert candidate_loss(evidence(mate=-8), evidence(mate=-10)) == 0
    choices = [evidence(mate=2), evidence(mate=8, uci="d2d4"), evidence(cp=0, uci="g1f3")]
    means = []
    for level in range(1, 5):
        rng = Random(72)
        losses = [candidate_loss(choices[0], choose_candidate(choices, level, rng)) for _ in range(2000)]
        means.append(sum(losses) / len(losses))
    assert all(left > right for left, right in zip(means, means[1:]))


def test_mate_in_one_is_checked_on_board_and_defenses_are_always_preferred():
    board = chess.Board()
    board.push_san("f3")
    board.push_san("e5")
    assert allows_mate_in_one(board, board.parse_san("g4"))
    assert not allows_mate_in_one(board, board.parse_san("g3"))
    choices = [evidence(500, uci="g2g4", allows_mate_in_one=True), evidence(-500, uci="g2g3")]
    for level in range(1, 5):
        assert choose_candidate(choices, level, Random(4))["uci"] == "g2g3"
        assert choose_candidate([evidence(mate=-1), evidence(-900, uci="d2d4")], level, Random(4))["uci"] == "d2d4"
    # A forced mating loss still produces a legal searched move.
    assert choose_candidate([evidence(mate=-1)], 1, Random(4))["uci"] == "e2e4"


class FakeEngine:
    options = {key: None for key in ("Threads", "Hash", "Skill Level", "UCI_LimitStrength")}

    def __init__(self):
        self.calls = []
        self.configured = None
        self.closed = False
        self.quit_called = False
        self.failure = False

    def configure(self, options):
        self.configured = options

    def analyse(self, board, limit, **kwargs):
        self.calls.append((board.copy(), limit, kwargs))
        if self.failure: raise chess.engine.EngineTerminatedError("process exited")
        moves = kwargs["root_moves"] or list(board.legal_moves)
        return [{"score": chess.engine.PovScore(chess.engine.Cp(30 - index * 25), board.turn),
                 "pv": [move], "depth": limit.depth} for index, move in enumerate(moves[:kwargs["multipv"]])]

    def close(self):
        self.closed = True

    def quit(self):
        self.quit_called = True


@pytest.fixture
def fake_worker(monkeypatch):
    fake = FakeEngine()
    starts = []
    def start(path, **kwargs):
        starts.append((path, kwargs))
        return fake
    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", start)
    service = OpponentService(lambda: "/stockfish")
    yield service, fake, starts
    service.close()


def test_worker_has_bounded_independent_configuration_and_compact_cached_evidence(fake_worker):
    service, fake, starts = fake_worker
    board = chess.Board()
    board.push_san("e4")
    original = board.fen()
    result = service.candidates(board, 1)
    assert fake.configured == {"Threads": 1, "Hash": 16, "Skill Level": 20, "UCI_LimitStrength": False}
    assert starts == [("/stockfish", {"timeout": 8})]
    assert len(result) == 16
    assert set(result[0]) == {"uci", "cp", "mate", "depth", "pv_uci", "allows_mate_in_one", "plausibility"}
    result[0]["cp"] = 9000
    assert service.candidates(board, 1)[0]["cp"] == 30
    assert len(fake.calls) == 1 and board.fen() == original
    service.candidates(chess.Board(board.fen()), 1)
    assert len(fake.calls) == 2  # The same FEN with different repetition history is a separate root.
    for level in (2, 3, 4):
        result = service.candidates(board, level)
        assert len(result) == PROFILES[level].pool
        _, limit, kwargs = fake.calls[-1]
        assert limit.time == PROFILES[level].time_ms / 1000 and limit.depth == PROFILES[level].depth
        assert kwargs["multipv"] == PROFILES[level].pool
    assert len({id(call[2]["game"]) for call in fake.calls}) == len(fake.calls)
    service.close()
    assert fake.quit_called and service._engine is None and not service._cache


def test_cache_expiry_and_size_are_bounded(fake_worker, monkeypatch):
    service, fake, _ = fake_worker
    clock = [1000.0]
    monkeypatch.setattr("src.backend.opponent.time.monotonic", lambda: clock[0])
    service.candidates(chess.Board(), 1)
    clock[0] += 301
    service.candidates(chess.Board(), 1)
    assert len(fake.calls) == 2
    for index in range(140):
        board = chess.Board()
        board.fullmove_number = index + 1
        service.candidates(board, 1)
    assert len(service._cache) == 128


def test_busy_worker_does_not_start_another_process(monkeypatch):
    service = OpponentService(lambda: "/stockfish")
    class BusyLock:
        def acquire(self, *, timeout):
            assert timeout == 2
            return False
    service._lock = BusyLock()
    with pytest.raises(OpponentUnavailable, match="busy"):
        service.candidates(chess.Board(), 1)
    assert service._engine is None


def test_failed_worker_is_closed_and_restart_is_backed_off(fake_worker):
    service, fake, starts = fake_worker
    fake.failure = True
    with pytest.raises(OpponentUnavailable, match="analysis failed"):
        service.candidates(chess.Board(), 1)
    assert fake.closed and service._engine is None
    with pytest.raises(OpponentUnavailable, match="unavailable"):
        service.candidates(chess.Board(), 1)
    assert len(starts) == 1 and not service._cache


def test_unsearched_mate_defense_is_searched_instead_of_random_fallback(fake_worker, monkeypatch):
    service, fake, _ = fake_worker
    board = chess.Board()
    board.push_san("f3")
    board.push_san("e5")
    calls = []
    def search(engine, position, profile, root_moves=None):
        calls.append(root_moves)
        if root_moves is None: return [evidence(mate=-1, uci="g2g4", allows_mate_in_one=True)]
        assert all(not allows_mate_in_one(position, move) for move in root_moves)
        assert position.parse_san("g3") in root_moves
        return [evidence(-50, uci=root_moves[0].uci())]
    monkeypatch.setattr(service, "_search", search)
    move = service.choose(board, 1, Random(713))
    assert move in board.legal_moves and not allows_mate_in_one(board, move)
    assert len(calls) == 2


def test_forced_and_terminal_positions_do_not_start_engine():
    service = OpponentService(lambda: None)
    board = chess.Board("8/8/8/8/8/q1k5/8/K7 w - - 0 1")
    assert service.choose(board, 1, Random(713)).uci() == "a1b1"
    assert service._engine is None
    with pytest.raises(ValueError, match="ended"):
        service.choose(chess.Board("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1"), 1, Random(713))


def test_engine_lifecycle_closes_opponent_and_translates_its_errors(monkeypatch):
    service = EngineService()
    closed = []
    monkeypatch.setattr(service._opponent, "close", lambda: closed.append(True))
    def unavailable(*args): raise OpponentUnavailable("practice unavailable")
    monkeypatch.setattr(service._opponent, "choose", unavailable)
    with pytest.raises(EngineUnavailable, match="practice unavailable"):
        service.play(chess.Board(), 1)
    service.close()
    assert closed == [True]


def test_real_beginner_opening_has_more_than_three_searched_moves(monkeypatch):
    import src.backend.engine as module
    service = EngineService()
    if not service.path(): pytest.skip("Stockfish not installed")
    monkeypatch.setattr(module, "random", Random(713))
    try:
        board = chess.Board()
        moves = [service.play(board, 1) for _ in range(96)]
        assert all(move in board.legal_moves for move in moves)
        assert len(set(moves)) > 3
        assert service._engine is None and service._opponent._engine is not None
        assert board.fen() == chess.STARTING_FEN
    finally:
        service.close()
