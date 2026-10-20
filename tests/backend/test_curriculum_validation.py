"""Multi-move lessons must verify the continuation, not just their first move."""
import copy

import chess
import chess.engine
import pytest

from scripts.validate_exercises import compare_decision, engine_path, verify
from src.backend.exercises import read_library


def test_rejects_legal_but_inferior_later_solver_move():
    item = copy.deepcopy(next(x for x in read_library() if x["id"] == "forks-08"))
    with chess.engine.SimpleEngine.popen_uci(engine_path()) as engine:
        engine.configure({"Threads": 1, "Hash": 64})
        evidence = verify(item, engine, .3)
        assert [step["ply"] for step in evidence["continuation_evidence"]] == [2, 3]
        # The fork itself is still correct, but this knight retreat misses the rook.
        item["solution"][-1] = "b5a3"
        with pytest.raises(ValueError, match="Unsound or shallow decision"):
            verify(item, engine, .3)


class ScoreSequenceEngine:
    def __init__(self, scores):
        self.scores = iter(scores)
        self.calls = []

    def analyse(self, board, limit, **kwargs):
        self.calls.append((limit.time, kwargs.get("root_moves")))
        return {"score": chess.engine.PovScore(next(self.scores), board.turn), "depth": 30}


@pytest.mark.parametrize("mixed", [
    (chess.engine.Cp(-935), chess.engine.Mate(-30)),
    (chess.engine.Mate(-30), chess.engine.Cp(-935)),
])
def test_mixed_losing_scores_get_one_bounded_warmed_recheck(mixed):
    engine = ScoreSequenceEngine([*mixed, *mixed, chess.engine.Mate(-29), chess.engine.Mate(-30)])
    board = chess.Board("7k/2R4p/8/1n6/3K4/8/8/8 w - - 1 2")
    move = chess.Move.from_uci("d4e5")
    _, _, budget = compare_decision(board, move, engine, .3)
    assert budget == 5
    assert [call[0] for call in engine.calls] == [.3, .3, 1.5, 1.5, 5, 5]
    # A chosen-root search precedes the final unrestricted search, warming its hash.
    assert engine.calls[3][1] == [move]
    assert engine.calls[4][1] is None


def test_unresolved_mixed_scores_are_not_accepted_as_equivalent():
    mixed = [chess.engine.Cp(-935), chess.engine.Mate(-30)]
    engine = ScoreSequenceEngine(mixed * 3)
    board = chess.Board("7k/2R4p/8/1n6/3K4/8/8/8 w - - 1 2")
    with pytest.raises(ValueError, match="Unsound or shallow decision"):
        compare_decision(board, chess.Move.from_uci("d4e5"), engine, .3)
    assert len(engine.calls) == 6


@pytest.mark.parametrize("scores", [
    [chess.engine.Cp(-500), chess.engine.Mate(-30)],
    [chess.engine.Cp(935), chess.engine.Mate(-30)],
    [chess.engine.Cp(-935), chess.engine.Cp(-1400)],
])
def test_other_inferior_scores_do_not_trigger_mate_horizon_recheck(scores):
    engine = ScoreSequenceEngine(scores * 2)
    board = chess.Board("7k/2R4p/8/1n6/3K4/8/8/8 w - - 1 2")
    with pytest.raises(ValueError, match="Unsound or shallow decision"):
        compare_decision(board, chess.Move.from_uci("d4e5"), engine, .3)
    assert len(engine.calls) == 4
