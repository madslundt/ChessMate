import chess
import asyncio
import threading

from src.backend.engine import engine_service


FEN = "6k1/5ppp/8/8/8/q7/1P3PPP/4R1K1 b - - 0 1"


def test_calculation_finds_first_error_and_mate_without_mutating_saved_game(signed):
    game = signed.post("/api/games", json={"mode": "analysis", "fen": FEN}).json()
    result = signed.post("/api/calculation", json={"fen": FEN, "moves": ["a3b2", "e1e8"],
                                                   "expected_evaluation": "winning"})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["fen"] == FEN and body["first_inaccuracy_ply"] == 1
    assert body["steps"][0]["classification"] == "Blunder"
    assert body["steps"][1]["role"] == "opponent_response"
    assert chess.Board(body["final_fen"]).is_checkmate()
    assert body["final_evaluation"] == "losing" and body["assessment_agrees"] is False
    assert "first weaker prediction" in body["text"]
    saved = signed.get(f"/api/games/{game['id']}").json()
    assert saved["fen"] == FEN and saved["moves"] == [] and saved["revision"] == game["revision"]


def test_invalid_later_prediction_is_rejected_before_engine_work(signed, monkeypatch):
    def unexpected(*_args, **_kwargs): raise AssertionError("Must validate entire line first")
    monkeypatch.setattr(engine_service, "grade", unexpected)
    result = signed.post("/api/calculation", json={"fen": chess.STARTING_FEN, "moves": ["e2e4", "a1a8"]})
    assert result.status_code == 422


def test_calculation_capacity_and_input_bounds(signed):
    from src.backend.calculation import slots
    slots.acquire()
    slots.acquire()
    try:
        assert signed.post("/api/calculation", json={"fen": FEN, "moves": ["a3b2"]}).status_code == 503
    finally:
        slots.release()
        slots.release()
    for changes in ({"time_ms": 501}, {"moves": []}, {"moves": ["a3b2"] * 65}, {"fen": "invalid"}):
        assert signed.post("/api/calculation", json={"fen": FEN, "moves": ["a3b2"], **changes}).status_code == 422


def test_final_evaluation_keeps_the_original_players_perspective(signed, monkeypatch):
    monkeypatch.setattr(engine_service, "grade", lambda *_args, **_kwargs: {
        "classification": "Good", "confidence": "engine_estimate", "text": "A legal candidate.", "best": {}})
    # After one white move it is Black's turn: a positive Black score is losing for the learner.
    monkeypatch.setattr(engine_service, "analyze", lambda board, **_kwargs: {
        "fen": board.fen(), "candidates": [{"cp": 350, "mate": None}]})
    response = signed.post("/api/calculation", json={"fen": chess.STARTING_FEN, "moves": ["e4"]})
    assert response.json()["final_evaluation"] == "losing"
    response = signed.post("/api/calculation", json={"fen": chess.STARTING_FEN, "moves": ["e4", "e5"]})
    assert response.json()["final_evaluation"] == "winning"


def test_canceled_calculation_retains_capacity_until_engine_thread_finishes(monkeypatch):
    from src.backend import calculation
    capacity, started, finish = threading.BoundedSemaphore(1), threading.Event(), threading.Event()
    monkeypatch.setattr(calculation, "slots", capacity)
    def blocking_grade(*_args, **_kwargs):
        started.set()
        finish.wait(timeout=3)
        return {}
    monkeypatch.setattr(engine_service, "grade", blocking_grade)
    class Connected:
        async def is_disconnected(self): return False
    async def scenario():
        task = asyncio.create_task(calculation.analyze_calculation(
            calculation.CalculationRequest(fen=chess.STARTING_FEN, moves=["e4"]), Connected(), None))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            await asyncio.sleep(0)
            reserved = not capacity.acquire(blocking=False)
            if not reserved: capacity.release()
            assert reserved, "Canceled request released capacity while engine work was still running"
        finally:
            finish.set()
            try: await task
            except asyncio.CancelledError: pass
        assert capacity.acquire(blocking=False)
        capacity.release()
    asyncio.run(scenario())
