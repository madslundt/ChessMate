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


def test_practice_comparison_samples_legal_moves_and_keeps_a_good_choice(monkeypatch):
    import copy
    import src.backend.engine as module
    from src.backend.engine import EngineService
    service = EngineService()
    board = chess.Board()
    original = {"fen": board.fen(), "candidates": [
        {"uci": uci, "cp": cp, "mate": None}
        for uci, cp in [("e2e4", 30), ("d2d4", 20), ("g1f3", -80)]
    ]}
    before = copy.deepcopy(original)
    calls = []

    def search(root, root_moves=None, **kwargs):
        assert root.fen() == board.fen()
        calls.append((root_moves, kwargs))
        if root_moves is None:
            return original
        return {"fen": root.fen(), "candidates": [
            {"uci": move.uci(), "cp": 30 if move.uci() == "d2d4" else -200,
             "mate": None, "pv_uci": [move.uci()]}
            for move in root_moves
        ]}

    monkeypatch.setattr(service, "analyze", search)
    def choose_good(choices):
        assert {choice["uci"] for choice in choices} == {"e2e4", "d2d4"}
        return choices[-1]
    monkeypatch.setattr(module.random, "choice", choose_good)
    def sample(choices, count):
        assert count == 2
        assert board.parse_san("d4") not in choices
        assert set(choices) == set(board.legal_moves) - {board.parse_san("d4")}
        return [board.parse_san("a3"), board.parse_san("h3")]
    monkeypatch.setattr(module.random, "sample", sample)

    result = service.compare(board, time_ms=100, depth=12)
    assert {c["uci"] for c in result["candidates"]} == {"d2d4", "a2a3", "h2h3"}
    assert len(result["candidates"]) == 3
    assert len(calls) == 2
    assert all(call[1] == {"time_ms": 100, "depth": 12, "candidates": 3} for call in calls)
    assert original == before  # Do not replace cached ranked analysis with practice candidates.
    assert board.fen() == chess.STARTING_FEN


@pytest.mark.parametrize("fen", [
    "8/8/8/8/8/6k1/5r2/7K w - - 0 1",  # Only Kh1-g1 is legal.
    "8/8/8/8/5k2/8/8/r6K w - - 0 1",  # Two legal king moves.
    "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",  # Checkmate.
    "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",  # Stalemate.
])
def test_practice_comparison_handles_fewer_than_three_choices(monkeypatch, fen):
    from src.backend.engine import EngineService
    service = EngineService()
    board = chess.Board(fen)
    legal = list(board.legal_moves)
    def search(root, root_moves=None, **kwargs):
        return {"fen": root.fen(), "candidates": [
            {"uci": move.uci(), "cp": 0, "mate": None}
            for move in (root_moves if root_moves is not None else legal)
        ]}
    monkeypatch.setattr(service, "analyze", search)
    result = service.compare(board)
    assert {c["uci"] for c in result["candidates"]} == {m.uci() for m in legal}


@pytest.mark.parametrize("fen", [
    chess.STARTING_FEN,
    "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
    "7k/P7/8/8/8/8/8/7K w - - 0 1",
])
def test_practice_analysis_api_returns_fresh_evaluated_choices(signed, monkeypatch, fen):
    import src.backend.engine as module
    if not engine_service.path(): pytest.skip("Stockfish not installed")
    # Keep the strongest candidate; change just the random alternatives between requests.
    monkeypatch.setattr(module.random, "choice", lambda choices: choices[0])
    samples = []
    def sample(choices, count):
        selected = choices[:count] if not samples else choices[-count:]
        samples.append(selected)
        return selected
    monkeypatch.setattr(module.random, "sample", sample)
    board = chess.Board(fen)
    ranked = signed.post("/api/analysis", json={"fen": fen, "time_ms": 100}).json()
    results = []
    for _ in range(2):
        response = signed.post("/api/analysis", json={
            "fen": fen, "time_ms": 100, "candidates": 1, "candidate_selection": "practice",
        })
        assert response.status_code == 200, response.text
        result = response.json()
        choices = result["candidates"]
        assert result["fen"] == fen
        assert result["perspective"] == ("white" if board.turn else "black")
        assert len({c["uci"] for c in choices}) == 3
        assert ranked["candidates"][0]["uci"] in {c["uci"] for c in choices}
        assert [score_number(c) for c in choices] == sorted([score_number(c) for c in choices], reverse=True)
        for candidate in choices:
            replay = board.copy()
            assert candidate["pv_uci"][0] == candidate["uci"]
            for uci in candidate["pv_uci"]:
                move = chess.Move.from_uci(uci)
                assert move in replay.legal_moves
                replay.push(move)
            assert candidate["insights"] and candidate["explanation"]
            assert candidate["white_cp"] == (candidate["cp"] if board.turn else
                                               -candidate["cp"] if candidate["cp"] is not None else None)
        results.append({c["uci"] for c in choices})
    assert results[0] != results[1]
    # Normal evaluation keeps its ranked cache and respects the one-candidate preference.
    normal = signed.post("/api/analysis", json={"fen": fen, "time_ms": 100, "candidates": 1})
    assert normal.status_code == 200
    assert len(normal.json()["candidates"]) == 1
    assert signed.post("/api/analysis", json={"fen": fen, "time_ms": 100}).json() == ranked


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


def grade_line(monkeypatch, board, played_san, line, best_san, language="en"):
    from src.backend.engine import EngineService
    service = EngineService()
    move = board.parse_san(played_san)
    replay = board.copy()
    pv = [replay.push_san(san).uci() for san in line]
    def search(root, root_moves=None, **kwargs):
        selected = move if root_moves else root.parse_san(best_san)
        return {"fen": root.fen(), "candidates": [{"uci": selected.uci(), "san": root.san(selected),
            "cp": -250 if root_moves else 50, "mate": None, "depth": 15,
            "pv": line if root_moves else [best_san], "pv_uci": pv if root_moves else [selected.uci()]}]}
    monkeypatch.setattr(service, "analyze", search)
    return service.grade(board, move, language=language)


@pytest.mark.parametrize("language", ["en", "da"])
@pytest.mark.parametrize("black", [False, True])
def test_bad_move_explains_material_lost_in_played_line(monkeypatch, language, black):
    board = chess.Board()
    board.push_san("e4")
    board.push_san("d5")
    moves = [board.parse_san("a3")]
    after = board.copy()
    after.push(moves[0])
    moves.append(after.parse_san("dxe4"))
    best = board.parse_san("exd5")
    if black:
        board = board.mirror()
        moves = [chess.Move(chess.square_mirror(m.from_square), chess.square_mirror(m.to_square)) for m in moves]
        best = chess.Move(chess.square_mirror(best.from_square), chess.square_mirror(best.to_square))
    replay = board.copy()
    line = []
    for move in moves:
        line.append(replay.san(move))
        replay.push(move)
    feedback = grade_line(monkeypatch, board, line[0], line, board.san(best), language)
    reason = feedback["consequence"]
    assert feedback["classification"] == "Blunder"
    assert board.san(best) not in reason
    assert ("net loss of material worth 1 pawn" if language == "en" else "nettotab af materiale svarende til 1 bonde") in reason
    victim = "pawn on e5" if black else "pawn on e4"
    assert (victim if language == "en" else "bonde") in reason
    assert ("other replies" if language == "en" else "andre svar") in reason.lower()
    threat = feedback["threats"][0]
    after = board.copy()
    after.push(moves[0])
    assert threat["fen"] == after.fen()
    assert threat["label"].startswith(line[1])
    assert ("pawn" if language == "en" else "bonde") in threat["label"]
    assert threat["arrows"] == [{"from": chess.square_name(moves[1].from_square), "to": chess.square_name(moves[1].to_square), "color": "red"}]
    assert feedback["improvement"] == {"uci": best.uci(), "san": board.san(best), "fen": board.fen()}


@pytest.mark.parametrize("language", ["en", "da"])
def test_bad_move_without_verified_cause_does_not_substitute_a_better_move(monkeypatch, language):
    feedback = grade_line(monkeypatch, chess.Board(), "a3", ["a3", "e5"], "e4", language)
    assert "e4" not in feedback["consequence"]
    assert ("not been verified" if language == "en" else "ikke verificeret") in feedback["consequence"]


@pytest.mark.parametrize("language", ["en", "da"])
def test_bad_capture_explanation_does_not_recommend_an_alternative(monkeypatch, language):
    board = chess.Board()
    board.push_san("e4")
    board.push_san("d5")
    feedback = grade_line(monkeypatch, board, "exd5", ["exd5", "Qxd5"], "Nc3", language)
    assert "Nc3" not in feedback["consequence"]
    assert "d5" in feedback["consequence"]
    assert "net loss" not in feedback["consequence"]
    assert "nettotab" not in feedback["consequence"]


def test_bad_move_explains_en_passant_capture_on_the_victims_square(monkeypatch):
    board = chess.Board("4k3/8/8/8/7p/8/6P1/4K3 w - - 0 1")
    feedback = grade_line(monkeypatch, board, "g4", ["g4", "hxg3"], "Kd2")
    assert "pawn on g4" in feedback["consequence"]
    assert "net loss of material worth 1 pawn" in feedback["consequence"]
    threat = feedback["threats"][0]
    assert "g4" in threat["squares"]
    assert threat["arrows"] == [{"from": "h4", "to": "g3", "color": "red"}]


@pytest.mark.parametrize("language", ["en", "da"])
def test_mating_threat_highlights_checker_and_king_in_the_verified_mated_position(monkeypatch, language):
    board = chess.Board()
    board.push_san("f3")
    board.push_san("e5")
    feedback = grade_line(monkeypatch, board, "g4", ["g4", "Qh4#"], "Nc3", language)
    threat = feedback["threats"][0]
    position = chess.Board(threat["fen"])
    assert position.is_checkmate()
    assert threat["label"] == ("Qh4# · skakmat" if language == "da" else "Qh4# · checkmate")
    assert set(threat["squares"]) == {"h4", "e1"}
    assert threat["arrows"] == [{"from": "h4", "to": "e1", "color": "red"}]


def test_geometric_threat_identifies_legal_capture_without_claiming_material_gain(monkeypatch):
    board = chess.Board()
    for san in ("e4", "e5", "Qh5", "Nc6"):
        board.push_san(san)
    feedback = grade_line(monkeypatch, board, "Qxe5+", ["Qxe5+"], "Bc4")
    threat = feedback["threats"][0]
    assert threat["claim_type"] == "board_geometry"
    assert "Queen e5" in threat["label"]
    assert "does not prove a material win" in threat["text"]
    root = chess.Board(threat["fen"])
    assert all(chess.Move.from_uci(arrow["from"] + arrow["to"]) in root.legal_moves for arrow in threat["arrows"])
