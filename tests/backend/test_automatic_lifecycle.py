"""Game commands -> durable analysis -> profile -> daily diary integration."""
from contextlib import contextmanager
from datetime import timedelta

import chess
from sqlalchemy import func, select

from src.backend import main
from src.backend.automatic_learning import AutomaticLearning, automatic_learning, ensure_completed
from src.backend.database import get_db
from src.backend.diary_models import DailyDiary
from src.backend.engine import EngineUnavailable, engine_service
from src.backend.learning_models import GameLearningAnalysis, LearningEvent
from src.backend.models import Game, User, now

MATE_IN_ONE = "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"


def session():
    return contextmanager(main.app.dependency_overrides[get_db])()


def grade(board, move, **_kwargs):
    candidate = {"uci": move.uci(), "depth": 12, "cp": None, "mate": 1}
    return {"fen": board.fen(), "move": move.uci(), "classification": "Good", "confidence": "engine_estimate",
        "text": "The queen gives checkmate.", "loss_cp": 0, "best": candidate, "played": candidate}


def finish(client, monkeypatch, assisted=False):
    automatic_learning.stop()  # Deterministically drive the persisted queue below.
    monkeypatch.setattr(engine_service, "grade", grade)
    created = client.post("/api/games", json={"fen": MATE_IN_ONE, "mode": "computer"})
    assert created.status_code == 201, created.text
    game = created.json()
    assert game["difficulty_mode"] == "adaptive" and game["difficulty"] == 1
    if assisted:
        for category in ("general_guidance", "piece_revealed", "destination_revealed"):
            response = client.post(f"/api/games/{game['id']}/assistance", json={"revision": 0, "fen": MATE_IN_ONE,
                "category": category, "source": "progressive_hint", "suggested_move": "f7g7"})
            assert response.status_code == 201, response.text
    finished = client.post(f"/api/games/{game['id']}/moves", json={"revision": 0, "move": "f7g7"})
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "checkmate"
    return finished.json()


def test_assisted_complete_game_updates_profile_and_diary_exactly_once(signed, monkeypatch):
    game = finish(signed, monkeypatch, assisted=True)
    initial = signed.get(f"/api/games/{game['id']}/learning").json()
    assert initial["status"] == "queued"
    worker = AutomaticLearning()
    assert worker.process_one(main.SessionLocal)
    done = signed.get(f"/api/games/{game['id']}/learning").json()
    assert done["status"] == "completed"
    observation = done["evidence"]["observations"][0]
    assert observation["assistance"] == "destination_revealed" and observation["followed_suggestion"]
    assert done["evidence"]["independent_assessed"] == 0
    profile = signed.get("/api/learning/profile").json()
    assert profile["sample_games"] == 1 and profile["adaptive_difficulty"] == 1
    assert profile["independent_assessed"] == 0
    day = done["completed_at"][:10]
    diary = signed.get("/api/diary/days/" + day).json()
    assert diary["status"] == "completed" and diary["statistics"]["assisted"] == 1
    assert diary["statistics"]["independent"] == 0
    assert len(diary["observations"]) == 1
    with session() as db:
        stored = db.get(Game, game["id"])
        ensure_completed(db, stored, db.get(User, stored.user_id))
        db.commit()
    assert not worker.process_one(main.SessionLocal)
    with session() as db:
        assert db.scalar(select(func.count(LearningEvent.id)).where(LearningEvent.kind == "game_observation")) == 1
        assert db.scalar(select(func.count(LearningEvent.id)).where(LearningEvent.kind == "assistance")) == 3
        assert db.scalar(select(func.count(DailyDiary.id))) == 1
    assert signed.get("/api/diary/days/" + day).json()["version"] == diary["version"]


def test_expired_worker_lease_resumes_after_restart_without_duplicate_evidence(signed, monkeypatch):
    game = finish(signed, monkeypatch)
    with session() as db:
        row = db.get(GameLearningAnalysis, game["id"])
        row.status, row.lease_token = "running", "interrupted-worker"
        row.lease_until = now() - timedelta(seconds=1)
        row.attempts = 1
        db.commit()
    restarted = AutomaticLearning()
    assert restarted.process_one(main.SessionLocal)
    done = signed.get(f"/api/games/{game['id']}/learning").json()
    assert done["status"] == "completed" and done["attempts"] == 2
    assert done["evidence"]["independent_assessed"] == 1
    assert not restarted.process_one(main.SessionLocal)
    with session() as db:
        assert db.scalar(select(func.count(LearningEvent.id)).where(LearningEvent.kind == "game_observation")) == 1
        assert db.get(GameLearningAnalysis, game["id"]).lease_token is None


def test_failed_engine_analysis_is_explicit_then_retries_to_one_final_diary(signed, monkeypatch):
    game = finish(signed, monkeypatch)
    with session() as db:
        stored = db.get(Game, game["id"])
        records = [dict(record) for record in stored.moves]
        records[0]["feedback"] = None
        stored.moves = records
        db.commit()
    def unavailable(*_args, **_kwargs): raise EngineUnavailable("Temporarily unavailable")
    monkeypatch.setattr(engine_service, "grade", unavailable)
    worker = AutomaticLearning()
    assert worker.process_one(main.SessionLocal)
    failed = signed.get(f"/api/games/{game['id']}/learning").json()
    assert failed["status"] == "failed" and failed["evidence"] is None
    day = failed["completed_at"][:10]
    diary = signed.get("/api/diary/days/" + day).json()
    assert diary["status"] == "failed" and diary["statistics"]["analyzed_games"] == 0
    assert not worker.process_one(main.SessionLocal)  # Backoff prevents a busy retry loop.
    with session() as db:
        row = db.get(GameLearningAnalysis, game["id"])
        row.next_attempt_at = now() - timedelta(seconds=1)
        db.commit()
    monkeypatch.setattr(engine_service, "grade", grade)
    assert worker.process_one(main.SessionLocal)
    ready = signed.get("/api/diary/days/" + day).json()
    assert ready["status"] == "completed" and ready["statistics"]["independent"] == 1
    with session() as db:
        assert db.scalar(select(func.count(DailyDiary.id))) == 1
        assert db.scalar(select(func.count(LearningEvent.id)).where(LearningEvent.kind == "game_observation")) == 1
