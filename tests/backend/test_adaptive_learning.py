"""Longitudinal evidence, assistance separation and bounded difficulty adjustments."""
from datetime import timedelta

import chess
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backend.automatic_learning import game_evidence, initial_profile, profile_for, project_profile, training_result
from src.backend.database import Base
from src.backend.learning_models import GameLearningAnalysis, LearningEvent
from src.backend.models import Game, GameEvent, User, now


@pytest.fixture
def evidence_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/evidence.db")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as db:
        user = User(name="longitudinal", preferences={})
        db.add(user)
        db.commit()
        yield db, user
    engine.dispose()


def positions():
    board = chess.Board()
    result = []
    for uci in "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 f1e1 b7b5 a4b3 d7d6 c2c3 e8g8".split():
        if board.turn: result.append(board.fen())
        board.push_uci(uci)
    return result


def analyzed_game(db, user, number, *, sound=False, assistance="independent", source="game", level=1, topic="forks"):
    completed = now() + timedelta(days=number)
    game = Game(user_id=user.id, initial_fen=chess.STARTING_FEN, moves=[], mode="computer",
        player_color="white", difficulty=level, learning_source=source, completed_at=completed)
    db.add(game)
    db.flush()
    observations = [{"game_id": game.id, "ply": index * 2 + 1, "fen": fen, "played_move": "e2e4",
        "san": "e4", "topic": topic, "skills": [], "classification": "Good" if sound else "Mistake",
        "sound": sound, "assistance": assistance, "source": source, "forced": False}
        for index, fen in enumerate(positions())]
    independent = assistance == "independent"
    db.add(GameLearningAnalysis(game_id=game.id, user_id=user.id, fingerprint=f"fixture{number}",
        status="completed", evidence={"observations": observations, "source": source,
            "independent_assessed": len(observations) if independent else 0,
            "independent_sound": len(observations) if independent and sound else 0,
            "opponent_difficulty": level}, updated_at=completed))
    db.commit()
    return game


def concept(profile, name="forks"):
    return next(item for item in profile["concepts"] if item["topic"] == name)


def test_one_game_cannot_establish_weakness_or_mastery(evidence_db):
    db, user = evidence_db
    analyzed_game(db, user, 1)
    profile = project_profile(db, user)
    assert concept(profile)["status"] == "insufficient_evidence"
    assert concept(profile)["games"] == 1
    assert profile["adaptive_difficulty"] == 1


def test_repeated_failures_then_independent_later_success_show_improvement(evidence_db):
    db, user = evidence_db
    for n in range(3): analyzed_game(db, user, n)
    profile = project_profile(db, user)
    assert concept(profile)["status"] == "recurring_weakness"
    for n in range(3, 6): analyzed_game(db, user, n, sound=True)
    profile = project_profile(db, user)
    assert concept(profile)["status"] == "improving"
    assert concept(profile)["games"] == 6
    assert all(item["fen"] and item["game_id"] for item in concept(profile)["evidence"])


def test_assisted_success_does_not_establish_independent_improvement(evidence_db):
    db, user = evidence_db
    for n in range(3): analyzed_game(db, user, n)
    for n in range(3, 7): analyzed_game(db, user, n, sound=True, assistance="full_solution")
    profile = project_profile(db, user)
    assert concept(profile)["status"] == "recurring_weakness"
    assert concept(profile)["independent_success_rate"] == 0
    assert profile["adaptive_difficulty"] == 1
    assert profile["assistance_counts"]["full_solution"] == 32


def test_unknown_and_training_never_inflate_estimated_game_strength(evidence_db):
    db, user = evidence_db
    for n in range(4): analyzed_game(db, user, n, sound=True, assistance="unknown", source="import")
    for n in range(4, 8): analyzed_game(db, user, n, sound=True, source="training")
    profile = project_profile(db, user)
    assert profile["adaptive_difficulty"] == 1
    assert profile["independent_assessed"] == 0
    assert profile["concepts"] == []


def test_difficulty_requires_four_consistent_games_and_does_not_reuse_them(evidence_db):
    db, user = evidence_db
    assert profile_for(db, user)["adaptive_difficulty"] == 1
    for n in range(3):
        analyzed_game(db, user, n, sound=True)
        assert project_profile(db, user)["adaptive_difficulty"] == 1
    analyzed_game(db, user, 3, sound=True)
    assert project_profile(db, user)["adaptive_difficulty"] == 2
    assert project_profile(db, user)["adaptive_difficulty"] == 2
    # One unusually poor game and one unusually good game cannot cause oscillation.
    analyzed_game(db, user, 4, sound=False, level=2)
    analyzed_game(db, user, 5, sound=True, level=2)
    assert project_profile(db, user)["adaptive_difficulty"] == 2


def test_decline_is_gradual_and_one_win_does_not_erase_it(evidence_db):
    db, user = evidence_db
    for n in range(4): analyzed_game(db, user, n, sound=True)
    assert project_profile(db, user)["adaptive_difficulty"] == 2
    for n in range(4, 8): analyzed_game(db, user, n, level=2)
    assert project_profile(db, user)["adaptive_difficulty"] == 1
    analyzed_game(db, user, 8, sound=True)
    assert project_profile(db, user)["adaptive_difficulty"] == 1


def test_manual_easy_opponents_cannot_raise_a_higher_adaptive_level(evidence_db):
    db, user = evidence_db
    for n in range(4): analyzed_game(db, user, n, sound=True)
    assert project_profile(db, user)["adaptive_difficulty"] == 2
    for n in range(4, 8): analyzed_game(db, user, n, sound=True, level=1)
    assert project_profile(db, user)["adaptive_difficulty"] == 2


def test_reanalysis_order_cannot_rewrite_chronology(evidence_db):
    db, user = evidence_db
    games = [analyzed_game(db, user, n, sound=n >= 3) for n in range(6)]
    old = db.get(GameLearningAnalysis, games[0].id)
    old.updated_at = now() + timedelta(days=100)
    db.commit()
    assert concept(project_profile(db, user))["status"] == "improving"


def test_no_encountered_opportunity_does_not_turn_a_weakness_into_strength(evidence_db):
    db, user = evidence_db
    for n in range(3): analyzed_game(db, user, n)
    for n in range(3, 8): analyzed_game(db, user, n, sound=True, topic="endgame")
    assert concept(project_profile(db, user))["status"] == "recurring_weakness"


def test_repeated_identical_position_in_one_game_does_not_establish_mastery(evidence_db):
    db, user = evidence_db
    game = analyzed_game(db, user, 0, sound=True)
    row = db.get(GameLearningAnalysis, game.id)
    observation = row.evidence["observations"][0]
    row.evidence = {**row.evidence, "observations": [observation] * 100}
    db.commit()
    profile = project_profile(db, user)
    assert concept(profile)["observations"] == 1
    assert concept(profile)["status"] == "insufficient_evidence"


def test_training_repetition_is_recorded_but_not_independent_mastery(evidence_db):
    db, user = evidence_db
    game = analyzed_game(db, user, 0, source="training")
    db.add(GameEvent(game_id=game.id, revision=0, kind="training_started", payload={
        "focus": "forks", "source": "own_game", "reference": "prior", "source_ply": 5, "repetition": 1}))
    db.flush()
    record = {"before_fen": chess.STARTING_FEN, "uci": "e2e4", "source": "player",
        "assistance": {"category": "independent"}, "feedback": {"classification": "Good", "confidence": "engine_estimate",
        "best": {"uci": "e2e4", "depth": 12}, "played": {"uci": "e2e4", "depth": 12}}}
    game.moves = [record]
    training_result(db, game, record)
    db.commit()
    events = db.query(LearningEvent).filter_by(kind="training_result").all()
    assert len(events) == 1
    assert events[0].payload["sound"] is True
    assert events[0].payload["independent"] is False
    assert events[0].payload["repeated_position"] is True


def test_default_adaptive_and_explicit_manual_strength_are_both_available(signed):
    automatic = signed.post("/api/games", json={"mode": "computer"}).json()
    manual = signed.post("/api/games", json={"mode": "computer", "difficulty": 4}).json()
    assert (automatic["difficulty_mode"], automatic["difficulty"]) == ("adaptive", 1)
    assert (manual["difficulty_mode"], manual["difficulty"]) == ("manual", 4)
    explicit = signed.post("/api/games", json={"mode": "computer", "difficulty": 4, "difficulty_mode": "adaptive"}).json()
    assert (explicit["difficulty_mode"], explicit["difficulty"]) == ("adaptive", 1)


def test_diary_pending_when_automation_disabled_and_undo_removes_empty_day(signed, monkeypatch):
    from src.backend import main
    from src.backend.automatic_learning import automatic_learning
    from src.backend.engine import engine_service
    from tests.backend.test_automatic_lifecycle import grade, MATE_IN_ONE
    automatic_learning.stop()
    monkeypatch.setattr(engine_service, "grade", grade)
    assert signed.patch("/api/settings", json={"automatic_analysis": False}).status_code == 200
    game = signed.post("/api/games", json={"mode": "training", "fen": MATE_IN_ONE}).json()
    game = signed.post(f"/api/games/{game['id']}/moves", json={"revision": 0, "move": "Qg7#"}).json()
    day = game["completed_at"][:10]
    diary = signed.get("/api/diary/days/" + day)
    assert diary.status_code == 200 and diary.json()["status"] == "pending"
    assert signed.post(f"/api/games/{game['id']}/learning/retry", json={}).status_code == 409
    undone = signed.post(f"/api/games/{game['id']}/undo", json={"revision": game["revision"]})
    assert undone.status_code == 200 and undone.json()["completed_at"] is None
    assert signed.get("/api/diary/days/" + day).status_code == 404
    replay = signed.post(f"/api/games/{game['id']}/redo", json={"revision": undone.json()["revision"]})
    assert replay.status_code == 200
    assert replay.json()["moves"][0]["assistance"]["category"] == "engine_assisted"


def test_retry_endpoint_resets_failed_queue_without_duplicate_work(signed, monkeypatch):
    from contextlib import contextmanager
    from src.backend import main
    from src.backend.database import get_db
    from tests.backend.test_automatic_lifecycle import finish
    game = finish(signed, monkeypatch)
    with contextmanager(main.app.dependency_overrides[get_db])() as db:
        row = db.get(GameLearningAnalysis, game["id"])
        row.status, row.attempts, row.error = "failed", 3, "Unavailable"
        db.commit()
    retry = signed.post(f"/api/games/{game['id']}/learning/retry", json={})
    assert retry.status_code == 202 and retry.json()["status"] == "queued"
    status = signed.get(f"/api/games/{game['id']}/learning").json()
    assert status["attempts"] == 0 and status["error"] is None
    active = signed.post("/api/games", json={}).json()
    assert signed.post(f"/api/games/{active['id']}/learning/retry", json={}).status_code == 409


def test_delivered_deep_analysis_is_recorded_once_even_on_repeated_polling(signed):
    from contextlib import contextmanager
    from src.backend import main
    from src.backend.analysis_jobs import record_job_disclosure
    from src.backend.database import get_db
    game = signed.post("/api/games", json={}).json()
    result = {"id": "cached-position-job", "fen": game["fen"], "status": "completed", "progress": {"game_id": game["id"]},
        "result": {"candidates": [{"uci": "e2e4"}]}}
    with contextmanager(main.app.dependency_overrides[get_db])() as db:
        user = db.get(User, signed.headers["X-Profile-ID"])
        record_job_disclosure(db, user, result)
        record_job_disclosure(db, user, result)
        events = db.query(LearningEvent).filter_by(kind="assistance").all()
        assert len(events) == 1 and events[0].payload["category"] == "engine_assisted"


def test_difficulty_explanation_uses_coaching_language(signed):
    assert signed.patch("/api/settings", json={"coach_language": "da"}).status_code == 200
    assert "Begyndervenligt" in signed.get("/api/learning/profile").json()["difficulty_reason"]


def test_weakness_without_recent_opportunities_remains_unknown_not_resolved(evidence_db):
    db, user = evidence_db
    for number in range(3): analyzed_game(db, user, number)
    previous = project_profile(db, user)
    assert concept(previous)["status"] == "recurring_weakness"
    db.commit()
    # Let the original fork opportunities fall outside the bounded game window.
    for number in range(3, 123): analyzed_game(db, user, number, sound=True, topic="opening")
    current = project_profile(db, user)
    stale = concept(current)
    assert stale["status"] == "insufficient_evidence"
    assert stale["previous_status"] == "recurring_weakness"
    assert stale["historical_observations"] == 24 and stale["observations"] == 0
    assert stale["independent_success_rate"] is None
    assert stale["evidence"] == concept(previous)["evidence"]
    db.commit()
    assert concept(project_profile(db, user))["previous_status"] == "recurring_weakness"
