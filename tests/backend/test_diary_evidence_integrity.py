"""Regression tests for evidence provenance across diary, reports and training."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import chess
import pytest
from sqlalchemy import select

from src.backend import gameplay_training, main
from src.backend.adaptive_diary import digest
from src.backend.database import get_db
from src.backend.diary_models import DailyDiary
from src.backend.engine import engine_service
from src.backend.learning_models import GameLearningAnalysis, LearningEvent, PlayerLearningState
from src.backend.models import GameEvent, User
from tests.backend.test_diary_lifecycle import seed_finished
from tests.backend.test_automatic_lifecycle import grade


def session():
    return contextmanager(main.app.dependency_overrides[get_db])()


def test_timezone_change_discards_profile_snapshot_from_after_local_day(signed):
    owner = signed.headers["X-Profile-ID"]
    with session() as db:
        seed_finished(db, owner, datetime(2026, 10, 22, 1, tzinfo=timezone.utc))
        db.add(PlayerLearningState(user_id=owner, updated_at=datetime(2026, 10, 22, 22, 30, tzinfo=timezone.utc), data={
            "adaptive_difficulty": 3, "sample_games": 6, "recommendations": [],
            "concepts": [{"topic": "forks", "status": "recurring_weakness", "independent": 24, "games": 6}]}))
        db.commit()
    before = signed.get("/api/diary/days/2026-10-22").json()
    assert before["profile_snapshot"]["as_of"].startswith("2026-10-22T22:30")
    assert "recurring difficulty" in before["summary"]
    # Tokyo's Oct 22 ends at 15:00 UTC. The game remains on the date,
    # but the previously saved late-evening learning conclusion is now future evidence.
    assert signed.patch("/api/settings", json={"timezone": "Asia/Tokyo"}).status_code == 200
    after = signed.get("/api/diary/days/2026-10-22").json()
    assert after["statistics"]["games"] == 1
    assert after["profile_snapshot"] is None
    assert "recurring difficulty" not in after["summary"]


def test_saved_snapshot_after_day_end_is_rejected_even_with_unchanged_timezone(signed):
    owner = signed.headers["X-Profile-ID"]
    with session() as db:
        seed_finished(db, owner, datetime(2026, 10, 22, 1, tzinfo=timezone.utc))
        db.commit()
    assert signed.get("/api/diary/days/2026-10-22").status_code == 200
    with session() as db:
        row = db.scalar(select(DailyDiary).where(DailyDiary.user_id == owner, DailyDiary.date == date(2026, 10, 22)))
        row.evidence = {**row.evidence, "profile_snapshot": {
            "as_of": "2026-10-23T00:30:00+00:00", "adaptive_difficulty": 5,
            "concepts": [{"topic": "forks", "status": "consistently_demonstrated_strength", "independent": 100, "games": 20}]}}
        row.fingerprint = digest({"evidence": row.evidence, "timezone": "UTC", "language": "en", "enabled": True})
        db.commit()
    after = signed.get("/api/diary/days/2026-10-22").json()
    assert after["profile_snapshot"] is None
    assert "consistently demonstrated strength" not in after["summary"]


def test_calendar_does_not_reuse_results_from_another_timezone(signed):
    owner = signed.headers["X-Profile-ID"]
    with session() as db:
        seed_finished(db, owner, datetime(2026, 10, 22, 1, tzinfo=timezone.utc))
        seed_finished(db, owner, datetime(2026, 10, 22, 23, 30, tzinfo=timezone.utc))
        db.commit()
    before = signed.get("/api/diary/days/2026-10-22").json()
    assert before["statistics"]["wins"] == 2
    signed.patch("/api/settings", json={"timezone": "Asia/Tokyo"})
    calendar = signed.get("/api/diary/calendar?month=2026-10").json()
    days = {day["date"]: day for day in calendar["days"]}
    assert days["2026-10-22"]["game_count"] == days["2026-10-23"]["game_count"] == 1
    assert days["2026-10-22"]["status"] == "pending"
    assert days["2026-10-22"]["wins"] == 0  # Old two-win daily projection is not reused.


@pytest.mark.parametrize("source", ["training", "import"])
def test_training_or_import_only_periods_never_establish_independent_game_comparison(signed, source):
    owner = signed.headers["X-Profile-ID"]
    with session() as db:
        for day in (21, 22):
            for hour in (8, 10, 12):
                game = seed_finished(db, owner, datetime(2026, 10, day, hour, tzinfo=timezone.utc))
                game.learning_source = source
                row = db.get(GameLearningAnalysis, game.id)
                observation = row.evidence["observations"][0]
                # Give both periods enough numeric observations and distinct games
                # that a source-blind comparison would wrongly declare them comparable.
                row.evidence = {"observations": [{**observation, "ply": index + 1, "source": source} for index in range(8)]}
        db.commit()
    for day in (21, 22):
        daily = signed.get(f"/api/diary/days/2026-10-{day}").json()
        assert daily["statistics"]["independent"] == 24
        assert daily["source_statistics"][source]["independent"] == 24
    response = signed.post("/api/diary/reports", json={"start_date": "2026-10-22", "end_date": "2026-10-22"})
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["statistics"]["analyzed_games"] == 3
    assert report["source_statistics"][source]["independent"] == 24
    assert report["comparison"]["source"] == "game"
    assert not report["comparison"]["sufficient_evidence"]
    assert report["comparison"]["independent_sound_rate_change"] is None
    assert report["comparison"]["statistics"]["independent"] == 0


def test_lifetime_training_exposure_survives_more_than_one_hundred_new_starts(signed, monkeypatch):
    owner = signed.headers["X-Profile-ID"]
    selected = gameplay_training.real_positions()[0]
    selected_key = selected["fen"].split()[:4]
    # A changed halfmove/fullmove count is still the same decision geometry.
    prior_fen = " ".join([*selected_key, "9", "42"])
    base = datetime(2026, 10, 22, 1, tzinfo=timezone.utc)
    with session() as db:
        db.add(LearningEvent(user_id=owner, kind="training_started", topic="mixed", fen=prior_fen,
            payload={"source": "classic"}, created_at=base))
        for index in range(101):
            db.add(LearningEvent(user_id=owner, kind="training_started", topic="mixed", fen=chess.STARTING_FEN,
                payload={"source": "other"}, created_at=base + timedelta(seconds=index + 1)))
        db.commit()
    monkeypatch.setattr(gameplay_training, "candidate_positions", lambda _db, _user, _focus: [dict(selected)])
    response = signed.post("/api/training/games", json={"focus": "mixed", "blind": True})
    assert response.status_code == 201, response.text
    game = response.json()
    with session() as db:
        started = db.scalar(select(GameEvent).where(GameEvent.game_id == game["id"], GameEvent.kind == "training_started"))
        assert started.payload["repetition"] == 1
    monkeypatch.setattr(engine_service, "grade", grade)
    played = signed.post(f"/api/games/{game['id']}/moves", json={"revision": 0, "move": game["legal_moves"][0]})
    assert played.status_code == 200, played.text
    with session() as db:
        result = db.scalar(select(LearningEvent).where(LearningEvent.kind == "training_result",
            LearningEvent.payload["game_id"].as_string() == game["id"]))
        assert result.payload["initial_decision"]
        assert result.payload["repeated_position"]
        assert not result.payload["independent"]
