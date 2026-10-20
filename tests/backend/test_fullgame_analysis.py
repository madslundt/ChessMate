import threading
import time
from types import SimpleNamespace

import pytest

from src.backend.engine import AnalysisCancelled, engine_service


def completed(client, identifier):
    for _ in range(200):
        value = client.get("/api/analysis/jobs/" + identifier).json()
        if value["status"] not in ("queued", "running"): return value
        time.sleep(.01)
    pytest.fail("Analysis job did not finish")


def game(client):
    response = client.post("/api/games", json={"mode": "analysis", "pgn": "1. e4 e5 2. Nf3 Nc6 *"})
    assert response.status_code == 201
    return response.json()


def grade(board, move, **kwargs):
    critical = move.uci() in ("e7e5", "b8c6")
    return {"fen": board.fen(), "move": move.uci(), "classification": "Mistake" if critical else "Good",
            "text": "Your move has been analyzed.", "confidence": "engine_estimate", "loss_cp": 150 if critical else 0,
            "analysis_mode": kwargs.get("mode", "quick"), "played": {}, "best": {}}


def test_fullgame_job_deep_verifies_critical_decisions_from_both_sides(signed, monkeypatch):
    calls = []
    def observe(board, move, **kwargs):
        calls.append((board.fen(), move.uci(), kwargs.get("mode", "quick"), kwargs["time_ms"]))
        return grade(board, move, **kwargs)
    monkeypatch.setattr(engine_service, "grade", observe)
    original = game(signed)
    response = signed.post(f"/api/games/{original['id']}/analysis-jobs", json={"revision": 0, "critical_time_ms": 7000})
    assert response.status_code == 202, response.text
    done = completed(signed, response.json()["id"])
    assert done["status"] == "completed" and done["result"]["complete"]
    assert done["result"]["critical_verified"] == 2
    assert [(move, budget) for _, move, mode, budget in calls if mode == "deep"] == [("e7e5", 7000), ("b8c6", 7000)]
    for root, move, mode, _ in calls:
        if mode == "deep": assert any(first_root == root and first_move == move and first_mode == "quick" for first_root, first_move, first_mode, _ in calls)
    result = signed.get(f"/api/games/{original['id']}").json()
    assert result["fen"] == original["fen"] and result["revision"] == 1
    assert result["moves"][1]["feedback"]["critical_verified"]
    assert "Black's" in result["moves"][1]["feedback"]["text"]


def test_cancelling_fullgame_job_interrupts_critical_search_without_mutating_game(signed, monkeypatch):
    entered = threading.Event()
    def search(board, move, **kwargs):
        if kwargs.get("mode") == "deep":
            entered.set()
            assert kwargs["cancel_event"].wait(3)
            raise AnalysisCancelled("cancelled")
        return grade(board, move, **kwargs)
    monkeypatch.setattr(engine_service, "grade", search)
    original = game(signed)
    response = signed.post(f"/api/games/{original['id']}/analysis-jobs", json={"revision": 0})
    assert entered.wait(1)
    cancelled = signed.delete("/api/analysis/jobs/" + response.json()["id"])
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    result = signed.get(f"/api/games/{original['id']}").json()
    assert result["revision"] == 0 and result["moves"] == original["moves"]


def test_fullgame_job_cannot_overwrite_moves_changed_during_analysis(signed, monkeypatch):
    entered, resume = threading.Event(), threading.Event()
    first = [True]
    def search(board, move, **kwargs):
        if kwargs.get("cancel_event") is not None and first[0]:
            first[0] = False
            entered.set()
            assert resume.wait(3)
        return grade(board, move, **kwargs)
    monkeypatch.setattr(engine_service, "grade", search)
    original = game(signed)
    response = signed.post(f"/api/games/{original['id']}/analysis-jobs", json={"revision": 0})
    assert entered.wait(1)
    moved = signed.post(f"/api/games/{original['id']}/moves", json={"revision": 0, "move": "Bb5"})
    assert moved.status_code == 200, moved.text
    resume.set()
    done = completed(signed, response.json()["id"])
    assert done["status"] == "failed" and "game changed" in done["error"].lower()
    current = signed.get(f"/api/games/{original['id']}").json()
    assert current["revision"] == 1 and current["moves"][-1]["san"] == "Bb5"
    assert all(record["feedback"] is None for record in current["moves"][:-1])


def test_time_bounded_fullgame_job_saves_a_resumable_partial_result(signed, monkeypatch):
    import src.backend.fullgame_analysis as fullgame
    clock = iter([0, 0, 901])
    monkeypatch.setattr(fullgame, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    monkeypatch.setattr(engine_service, "grade", grade)
    original = game(signed)
    response = signed.post(f"/api/games/{original['id']}/analysis-jobs", json={"revision": 0})
    first = completed(signed, response.json()["id"])
    assert first["status"] == "completed" and not first["result"]["complete"]
    assert first["result"]["next_ply"] == 1 and first["result"]["revision"] == 1
    monkeypatch.setattr(fullgame, "time", SimpleNamespace(monotonic=lambda: 0))
    response = signed.post(f"/api/games/{original['id']}/analysis-jobs", json={"revision": 1, "start_ply": 1})
    second = completed(signed, response.json()["id"])
    assert second["status"] == "completed" and second["result"]["complete"]
    assert second["result"]["next_ply"] == 4 and second["result"]["revision"] == 2
