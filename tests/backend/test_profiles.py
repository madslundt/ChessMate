from datetime import timedelta

import chess
import pytest
from sqlalchemy import select

import src.backend.main as main
from src.backend.models import AuthSession, CoachingMessage, Game, GameEvent, HintUsage, LlmConnection, User, now
from src.backend.training_models import Exercise, ExerciseAttempt, HintEvent, LearningProgress, OpeningLine, TrainingSession


def test_profiles_are_public_without_passwords_and_can_be_renamed(client):
    assert client.get("/api/profiles").json() == []
    created = client.post("/api/profiles", json={"name": "  Learner  "})
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["name"] == "Learner"
    assert set(profile) == {"id", "name", "preferences"}
    assert profile["preferences"]["auto_computer"] is True
    assert client.get("/api/profiles").json() == [profile]
    renamed = client.patch(f"/api/profiles/{profile['id']}", json={"name": "New name"})
    assert renamed.status_code == 200
    assert renamed.json() == {**profile, "name": "New name"}
    assert client.get("/api/profiles").json() == [renamed.json()]


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
def test_invalid_profile_names_are_rejected_for_create_and_update(client, name):
    profile = client.post("/api/profiles", json={"name": "Original"}).json()
    assert client.post("/api/profiles", json={"name": name}).status_code == 422
    assert client.patch(f"/api/profiles/{profile['id']}", json={"name": name}).status_code == 422
    assert client.get("/api/profiles").json() == [profile]


def test_profile_names_are_unique_ignoring_case_and_whitespace(client):
    first = client.post("/api/profiles", json={"name": "Learner"}).json()
    other = client.post("/api/profiles", json={"name": "Other"}).json()
    assert client.post("/api/profiles", json={"name": " learner "}).status_code == 409
    assert client.patch(f"/api/profiles/{other['id']}", json={"name": "LEARNER"}).status_code == 409
    same = client.patch(f"/api/profiles/{first['id']}", json={"name": "LEARNER"})
    assert same.status_code == 200 and same.json()["id"] == first["id"]
    assert len(client.get("/api/profiles").json()) == 2


def test_missing_or_removed_profile_cannot_access_profile_data(client):
    assert client.get("/api/settings").status_code == 400
    client.headers["X-Profile-ID"] = "missing-profile"
    assert client.get("/api/settings").status_code == 404
    assert client.patch("/api/profiles/missing-profile", json={"name": "Nobody"}).status_code == 404
    assert client.delete("/api/profiles/missing-profile").status_code == 404
    profile = client.post("/api/profiles", json={"name": "Temporary"}).json()
    client.headers["X-Profile-ID"] = profile["id"]
    assert client.get("/api/settings").status_code == 200
    deleted = client.delete(f"/api/profiles/{profile['id']}")
    assert deleted.status_code == 204 and deleted.content == b""
    assert client.get("/api/settings").status_code == 404
    assert client.get("/api/profiles").json() == []


def test_legacy_users_are_selectable_without_exposing_password_hashes(client):
    with main.SessionLocal() as db:
        user = User(name="Existing user", password_hash="legacy-password-hash", preferences={"auto_computer": False})
        db.add(user)
        db.commit()
        profile_id = user.id
    response = client.get("/api/profiles")
    assert response.status_code == 200 and "legacy-password-hash" not in response.text
    assert "password_hash" not in response.text
    client.headers["X-Profile-ID"] = profile_id
    assert client.get("/api/settings").json()["auto_computer"] is False


def test_delete_profile_removes_owned_records_and_preserves_other_profiles(signed):
    profile_id = signed.headers["X-Profile-ID"]
    other = signed.post("/api/profiles", json={"name": "Keep me"}).json()
    with main.SessionLocal() as db:
        # Enforce the production foreign-key behavior for this deletion regression.
        db.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
        game = Game(user_id=profile_id, initial_fen=chess.STARTING_FEN)
        other_game = Game(user_id=other["id"], initial_fen=chess.STARTING_FEN)
        db.add_all([game, other_game])
        db.flush()
        game_id, other_game_id = game.id, other_game.id
        exercise = Exercise(id="owned-exercise", category="forks", data={}, owner_id=profile_id, source_game_id=game_id)
        db.add(exercise)
        db.flush()
        db.add_all([
            GameEvent(game_id=game_id, revision=0, kind="create", payload={}),
            CoachingMessage(user_id=profile_id, game_id=game_id, fen=chess.STARTING_FEN, role="user", content="Question"),
            HintUsage(user_id=profile_id, fen=chess.STARTING_FEN, level=1),
            LlmConnection(user_id=profile_id, base_url="http://model/v1", model="fixture", api_key="private-fixture-key"),
            AuthSession(token_hash="legacy-session", user_id=profile_id, expires_at=now() + timedelta(days=1)),
            ExerciseAttempt(user_id=profile_id, exercise_id=exercise.id, topic="forks", moves=[], correct=False, complete=False),
            HintEvent(user_id=profile_id, exercise_id=exercise.id, level=1),
            LearningProgress(user_id=profile_id, exercise_id=exercise.id, topic="forks"),
            TrainingSession(user_id=profile_id, kind="daily", minutes=5, exercise_ids=[exercise.id]),
            OpeningLine(user_id=profile_id, name="Opening", color="white", initial_fen=chess.STARTING_FEN, moves=["e2e4"]),
            LlmConnection(user_id=other["id"], base_url="http://other/v1", model="keep-model"),
        ])
        db.commit()
    deleted = signed.delete(f"/api/profiles/{profile_id}")
    assert deleted.status_code == 204, deleted.text
    assert signed.get("/api/profiles").json() == [other]
    with main.SessionLocal() as db:
        assert db.get(User, profile_id) is None
        assert db.get(Game, game_id) is None
        assert db.get(Exercise, "owned-exercise") is None
        for model in (CoachingMessage, HintUsage, LlmConnection, AuthSession, ExerciseAttempt, HintEvent,
                      LearningProgress, TrainingSession, OpeningLine):
            assert db.scalar(select(model).where(model.user_id == profile_id)) is None
        assert db.scalar(select(GameEvent).where(GameEvent.game_id == game_id)) is None
        assert db.get(Game, other_game_id) is not None
        assert db.get(LlmConnection, other["id"]).model == "keep-model"
        assert db.scalar(select(Exercise).where(Exercise.owner_id.is_(None))) is not None
