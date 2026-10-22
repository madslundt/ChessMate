"""Daily aggregation/report contracts, independent of engine or optional inference."""
from contextlib import contextmanager
from datetime import date, datetime, timezone

import chess
from sqlalchemy import func, select

from src.backend import main
from src.backend.adaptive_diary import rebuild_day
from src.backend.database import get_db
from src.backend.diary_models import DailyDiary, ProgressReport
from src.backend.learning_models import GameLearningAnalysis
from src.backend.models import Game, User

START = "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"


def session():
    return contextmanager(main.app.dependency_overrides[get_db])()


def seed_finished(db, owner, completed, category="independent", analyzed=True):
    board = chess.Board(START)
    move = chess.Move.from_uci("f7g7")
    record = {"uci": move.uci(), "san": board.san(move), "before_fen": board.fen(), "color": "white", "source": "player"}
    board.push(move)
    record["fen"] = board.fen()
    game = Game(user_id=owner, initial_fen=START, moves=[record], mode="computer",
        player_color="white", difficulty=2, completed_at=completed)
    db.add(game)
    db.flush()
    if analyzed:
        observation = {"ply": 1, "fen": START, "san": "Qg7#", "played_move": move.uci(),
            "topic": "endgame", "skills": ["calculation"], "classification": "Good",
            "sound": True, "assistance": category, "engine_analysis": {"text": "The queen gives checkmate."}}
        db.add(GameLearningAnalysis(game_id=game.id, user_id=owner, status="completed",
            fingerprint=game.id, evidence={"observations": [observation]}))
    return game


def test_diary_uses_completion_timezone_and_regeneration_is_idempotent(signed):
    owner = signed.headers["X-Profile-ID"]
    assert signed.patch("/api/settings", json={"timezone": "Europe/Copenhagen"}).status_code == 200
    with session() as db:
        game = seed_finished(db, owner, datetime(2026, 10, 21, 22, 30, tzinfo=timezone.utc))
        game.created_at = datetime(2026, 10, 20, 10, tzinfo=timezone.utc)
        db.commit()
    calendar = signed.get("/api/diary/calendar?month=2026-10").json()
    assert calendar["days"] == [{"date": "2026-10-22", "game_count": 1, "status": "pending", "wins": 0, "draws": 0, "losses": 0}]
    first = signed.get("/api/diary/days/2026-10-22")
    assert first.status_code == 200, first.text
    diary = first.json()
    assert diary["statistics"]["games"] == diary["statistics"]["wins"] == diary["statistics"]["independent"] == 1
    assert diary["games"][0]["id"] == game.id and diary["observations"][0]["fen"] == START
    assert signed.get("/api/diary/days/2026-10-21").status_code == 404
    for _ in range(3):
        regenerated = signed.post("/api/diary/days/2026-10-22/regenerate", json={}).json()
        assert regenerated["version"] == diary["version"]
        assert regenerated["statistics"] == diary["statistics"]
    with session() as db:
        assert db.scalar(select(func.count(DailyDiary.id))) == 1
        assert db.scalar(select(func.count(ProgressReport.id))) == 0


def test_same_day_updates_partial_status_and_separates_assistance(signed):
    owner = signed.headers["X-Profile-ID"]
    with session() as db:
        seed_finished(db, owner, datetime(2026, 10, 22, 9, tzinfo=timezone.utc), "full_solution")
        pending = seed_finished(db, owner, datetime(2026, 10, 22, 10, tzinfo=timezone.utc), analyzed=False)
        seed_finished(db, owner, datetime(2026, 10, 22, 11, tzinfo=timezone.utc), "unknown")
        db.commit()
    first = signed.get("/api/diary/days/2026-10-22").json()
    assert first["status"] == "partial" and "incomplete" in first["summary"]
    assert first["statistics"]["games"] == 3 and first["statistics"]["analyzed_games"] == 2
    assert first["statistics"]["independent"] == 0 and first["statistics"]["assisted"] == first["statistics"]["unknown"] == 1
    with session() as db:
        db.add(GameLearningAnalysis(game_id=pending.id, user_id=owner, status="completed", fingerprint=pending.id,
            evidence={"observations": []}))
        db.commit()
    second = signed.get("/api/diary/days/2026-10-22").json()
    assert second["status"] == "completed" and second["version"] == first["version"] + 1
    assert second["statistics"]["analyzed_games"] == 3
    with session() as db:
        assert db.scalar(select(func.count(DailyDiary.id))) == 1


def test_reports_use_owned_diary_evidence_save_reopen_and_mark_changed_days(signed):
    owner = signed.headers["X-Profile-ID"]
    with session() as db:
        user = db.get(User, owner)
        for day in (21, 22):
            seed_finished(db, owner, datetime(2026, 10, day, 10, tzinfo=timezone.utc))
            rebuild_day(db, user, date(2026, 10, day))
        db.commit()
    response = signed.post("/api/diary/reports", json={"start_date": "2026-10-21", "end_date": "2026-10-22"})
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["active_days"] == report["statistics"]["games"] == 2
    assert len(report["observations"]) == 2 and not report["outdated"]
    assert not report["comparison"]["sufficient_evidence"] and report["comparison"]["independent_sound_rate_change"] is None
    assert signed.get(f"/api/diary/reports/{report['id']}").json() == report
    with session() as db:
        user = db.get(User, owner)
        seed_finished(db, owner, datetime(2026, 10, 22, 11, tzinfo=timezone.utc), "general_guidance")
        rebuild_day(db, user, date(2026, 10, 22))
        db.commit()
    assert signed.get(f"/api/diary/reports/{report['id']}").json()["outdated"]
    renewed = signed.post(f"/api/diary/reports/{report['id']}/regenerate", json={}).json()
    assert renewed["statistics"]["games"] == 3 and not renewed["outdated"]
    assert len(renewed["observations"]) == 3
    stranger = signed.post("/api/profiles", json={"name": "diary-outsider"}).json()
    signed.headers["X-Profile-ID"] = stranger["id"]
    assert signed.get("/api/diary/calendar?month=2026-10").json()["days"] == []
    assert signed.get("/api/diary/days/2026-10-22").status_code == 404
    assert signed.get("/api/diary/reports").json() == []
    assert signed.get(f"/api/diary/reports/{report['id']}").status_code == 404
    assert signed.post(f"/api/diary/reports/{report['id']}/regenerate", json={}).status_code == 404


def test_empty_reports_invalid_ranges_and_missing_diaries_are_explicit(signed):
    empty = signed.post("/api/diary/reports", json={"start_date": "2026-10-01", "end_date": "2026-10-31"}).json()
    assert empty["statistics"]["games"] == empty["active_days"] == 0
    assert not empty["comparison"]["sufficient_evidence"]
    for data in ({"start_date": "2026-10-31", "end_date": "2026-10-01"},
                 {"start_date": "2026-99-01", "end_date": "2026-10-31"}):
        assert signed.post("/api/diary/reports", json=data).status_code == 422
    assert signed.get("/api/diary/calendar?month=2026-13").status_code == 422
    assert signed.patch("/api/settings", json={"timezone": "Not/A_Zone"}).status_code == 422
    with session() as db:
        seed_finished(db, signed.headers["X-Profile-ID"], datetime(2026, 10, 22, 10, tzinfo=timezone.utc))
        db.commit()
    report = signed.post("/api/diary/reports", json={"start_date": "2026-10-01", "end_date": "2026-10-31"}).json()
    assert report["status"] == "partial" and report["missing_diary_games"] == 1


def test_diary_language_and_disabled_automatic_narrative_preserve_structured_data(signed):
    owner = signed.headers["X-Profile-ID"]
    signed.patch("/api/settings", json={"coach_language": "da", "automatic_diary": False})
    with session() as db:
        seed_finished(db, owner, datetime(2026, 10, 22, 10, tzinfo=timezone.utc))
        db.commit()
    disabled = signed.get("/api/diary/days/2026-10-22").json()
    assert disabled["summary"] == "" and disabled["statistics"]["games"] == 1
    explicit = signed.post("/api/diary/days/2026-10-22/regenerate", json={}).json()
    assert "Du afsluttede 1 parti" in explicit["summary"]
    assert signed.get("/api/diary/days/2026-10-22").json()["summary"] == explicit["summary"]
    assert explicit["observations"][0]["game_id"]


def test_saved_report_marks_new_game_outdated_before_diary_is_rebuilt(signed):
    owner = signed.headers["X-Profile-ID"]
    with session() as db:
        seed_finished(db, owner, datetime(2026, 10, 22, 10, tzinfo=timezone.utc))
        rebuild_day(db, db.get(User, owner), date(2026, 10, 22))
        db.commit()
    report = signed.post("/api/diary/reports", json={"start_date": "2026-10-22", "end_date": "2026-10-22"}).json()
    assert not report["outdated"]
    with session() as db:
        seed_finished(db, owner, datetime(2026, 10, 22, 11, tzinfo=timezone.utc))
        db.commit()
    changed = signed.get(f"/api/diary/reports/{report['id']}").json()
    assert changed["outdated"]
    assert changed["statistics"]["games"] == 1  # Saved snapshot remains reproducible.
    renewed = signed.post(f"/api/diary/reports/{report['id']}/regenerate", json={}).json()
    assert renewed["status"] == "partial" and renewed["missing_diary_games"] == 1
    assert "incomplete" in renewed["summary"]


def test_timezone_change_does_not_double_count_previous_local_day_diaries(signed):
    owner = signed.headers["X-Profile-ID"]
    with session() as db:
        seed_finished(db, owner, datetime(2026, 10, 21, 23, tzinfo=timezone.utc))
        rebuild_day(db, db.get(User, owner), date(2026, 10, 21))
        db.commit()
    signed.patch("/api/settings", json={"timezone": "Europe/Copenhagen"})
    stale = signed.post("/api/diary/reports", json={"start_date": "2026-10-21", "end_date": "2026-10-22"}).json()
    assert stale["status"] == "partial" and stale["missing_diary_games"] == 1
    assert stale["statistics"]["games"] == 0
    assert signed.get("/api/diary/days/2026-10-22").status_code == 200
    fresh = signed.post("/api/diary/reports", json={"start_date": "2026-10-21", "end_date": "2026-10-22"}).json()
    assert fresh["statistics"]["games"] == 1 and len(fresh["observations"]) == 1


def test_calendar_boundaries_reject_dates_that_cannot_be_safely_projected(signed):
    for month in ("9999-12", "0001-01", "0000-01"):
        assert signed.get(f"/api/diary/calendar?month={month}").status_code == 422
    for day in ("9999-12-31", "0001-01-01"):
        assert signed.get(f"/api/diary/days/{day}").status_code == 422
        assert signed.post(f"/api/diary/days/{day}/regenerate", json={}).status_code == 422
