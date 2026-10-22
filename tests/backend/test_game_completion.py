"""Non-board completion must retain a result and enter the normal learning lifecycle."""
from contextlib import contextmanager

import chess
import pytest
from sqlalchemy import select

from src.backend import main
from src.backend.automatic_learning import AutomaticLearning, automatic_learning
from src.backend.database import get_db
from src.backend.engine import engine_service
from src.backend.learning_models import GameLearningAnalysis, LearningEvent
from src.backend.models import Game, User


def session():
    return contextmanager(main.app.dependency_overrides[get_db])()


def grade(board, move, **kwargs):
    candidate = {"uci": move.uci(), "depth": 12, "cp": 0, "mate": None}
    return {"fen": board.fen(), "move": move.uci(), "classification": "Good", "confidence": "engine_estimate",
        "text": "A reasonable legal move.", "loss_cp": 0, "best": candidate, "played": candidate}


@pytest.mark.parametrize("result", ["1-0", "0-1", "1/2-1/2"])
def test_completed_import_without_terminal_board_is_analyzed_and_preserves_result(signed, monkeypatch, result):
    automatic_learning.stop()
    monkeypatch.setattr(engine_service, "grade", grade)
    response = signed.post("/api/games", json={"mode": "analysis", "pgn": f'[Result "{result}"]\n\n1. e4 e5 2. Nf3 {result}'})
    assert response.status_code == 201, response.text
    game = response.json()
    assert not chess.Board(game["fen"]).is_game_over()
    assert game["result"] == result and game["completed_at"]
    assert game["completion_reason"] == "imported_result"
    status = signed.get(f"/api/games/{game['id']}/learning").json()
    assert status["status"] == "queued"
    worker = AutomaticLearning()
    assert worker.process_one(main.SessionLocal)
    status = signed.get(f"/api/games/{game['id']}/learning").json()
    assert status["status"] == "completed" and status["evidence"]["result"] == result
    assert status["evidence"]["independent_assessed"] == 0
    assert all(item["assistance"] == "unknown" for item in status["evidence"]["observations"])
    exported = signed.get(f"/api/games/{game['id']}/pgn")
    assert f'[Result "{result}"]' in exported.text
    assert exported.text.rstrip().endswith(result)
    day = game["completed_at"][:10]
    diary = signed.get("/api/diary/days/" + day)
    assert diary.status_code == 200, diary.text
    statistics = diary.json()["statistics"]
    assert statistics["games"] == 1
    key = "wins" if result == "1-0" else "losses" if result == "0-1" else "draws"
    assert statistics[key] == 1
    assert signed.post(f"/api/games/{game['id']}/moves", json={"revision": 1, "move": "Nc6"}).status_code == 409


@pytest.mark.parametrize("color,result", [("white", "0-1"), ("black", "1-0")])
def test_resignation_finishes_owned_game_queues_learning_and_blocks_further_moves(signed, monkeypatch, color, result):
    automatic_learning.stop()
    monkeypatch.setattr(engine_service, "grade", grade)
    # A nonterminal import lets either player color resign after actual play.
    response = signed.post("/api/games", json={"mode": "training", "player_color": color, "pgn": "1. e4 e5 *"})
    game = response.json()
    resigned = signed.post(f"/api/games/{game['id']}/resign", json={"revision": 0})
    assert resigned.status_code == 200, resigned.text
    game = resigned.json()
    assert game["result"] == result and game["status"] == "resignation"
    assert game["completion_reason"] == "resignation" and game["revision"] == 1 and game["completed_at"]
    assert signed.get(f"/api/games/{game['id']}/learning").json()["status"] == "queued"
    for route, body in (("moves", {"revision": 1, "move": "Nf3"}), ("computer", {"revision": 1}), ("resign", {"revision": 1})):
        assert signed.post(f"/api/games/{game['id']}/" + route, json=body).status_code == 409
    assert signed.get(f"/api/games/{game['id']}/review").json()["result"] == result
    export = signed.get(f"/api/games/{game['id']}/pgn").text
    assert '[Termination "resignation"]' in export and export.rstrip().endswith(result)
    with session() as db:
        stored = db.get(Game, game["id"])
        assert stored.result_override == result and stored.completion_reason == "resignation"


def test_resignation_rejects_empty_analysis_foreign_and_stale_games(signed):
    automatic_learning.stop()
    empty = signed.post("/api/games", json={"mode": "computer"}).json()
    assert signed.post(f"/api/games/{empty['id']}/resign", json={"revision": 0}).status_code == 409
    analysis = signed.post("/api/games", json={"mode": "analysis", "pgn": "1. e4 *"}).json()
    assert signed.post(f"/api/games/{analysis['id']}/resign", json={"revision": 0}).status_code == 409
    game = signed.post("/api/games", json={"pgn": "1. e4 e5 *"}).json()
    assert signed.post(f"/api/games/{game['id']}/resign", json={"revision": 9}).status_code == 409
    stranger = signed.post("/api/profiles", json={"name": "completion-outsider"}).json()
    signed.headers["X-Profile-ID"] = stranger["id"]
    assert signed.post(f"/api/games/{game['id']}/resign", json={"revision": 0}).status_code == 404


def test_undo_reopens_imported_finished_game_and_removes_the_old_daily_entry(signed):
    automatic_learning.stop()
    game = signed.post("/api/games", json={"mode": "training", "pgn": '[Result "1-0"]\n\n1. e4 e5 1-0'}).json()
    day = game["completed_at"][:10]
    assert signed.get("/api/diary/days/" + day).status_code == 200
    undone = signed.post(f"/api/games/{game['id']}/undo", json={"revision": 0})
    assert undone.status_code == 200, undone.text
    current = undone.json()
    assert current["result"] == "*" and current["completed_at"] is None
    assert current["completion_reason"] is None
    assert signed.get("/api/diary/days/" + day).status_code == 404
    with session() as db:
        stored = db.get(Game, game["id"])
        assert stored.result_override is None
        assert db.get(GameLearningAnalysis, game["id"]).status == "cancelled"


def test_import_rejects_invalid_or_contradictory_result_and_keeps_unfinished_games_active(signed):
    automatic_learning.stop()
    invalid = signed.post("/api/games", json={"pgn": '[Result "2-0"]\n\n1. e4 e5 *'})
    assert invalid.status_code == 422
    contradictory = signed.post("/api/games", json={"pgn": '[Result "1-0"]\n\n1. f3 e5 2. g4 Qh4# 1-0'})
    assert contradictory.status_code == 422
    active = signed.post("/api/games", json={"pgn": "1. e4 e5 *"}).json()
    assert active["result"] == "*" and active["completed_at"] is None
    assert signed.get(f"/api/games/{active['id']}/learning").json()["status"] == "not_queued"
