from collections import Counter
from datetime import timedelta

import chess
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.backend import auth, training
from src.backend.database import Base, get_db
from src.backend.engine import EngineUnavailable
from src.backend.exercises import CATEGORIES, objective_met, parse_move, read_library, validate_structure
from src.backend.models import HintUsage, User, now
from src.backend.training_models import Exercise, ExerciseAttempt, HintEvent, LearningProgress


@pytest.fixture
def training_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(auth.router, prefix="/api")
    app.include_router(training.router, prefix="/api")
    def db_override():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = db_override
    with sessions() as db:
        training.seed_exercises(db)
    with TestClient(app) as client:
        response = client.post("/api/profiles", json={"name": "trainee"})
        assert response.status_code == 201, response.text
        client.headers["X-Profile-ID"] = response.json()["id"]
        yield client, sessions
    engine.dispose()


def test_original_library_is_legal_complete_and_does_not_reveal_answers():
    library = read_library()
    counts = Counter(x["category"] for x in library)
    assert set(counts) == set(CATEGORIES)
    assert all(counts[category] >= 8 for category in CATEGORIES)
    assert len({x["fen"] for x in library}) == len(library)
    for exercise in library:
        board = validate_structure(exercise)
        assert exercise["evidence"]["objective_verified"]
        assert exercise["evidence"]["engine"].startswith("Stockfish")
        assert exercise["evidence"]["depth"] >= 8
        assert objective_met(board, parse_move(board, exercise["solution"][0]), exercise["criterion"])
        for move in exercise["evidence"]["pv_uci"]:
            board.push(parse_move(board, move))


def test_api_requires_selected_profile_and_hides_solutions(training_client):
    client, _ = training_client
    profile_id = client.headers.pop("X-Profile-ID")
    assert client.get("/api/exercises").status_code == 400
    assert client.get("/api/progress").status_code == 400
    client.headers["X-Profile-ID"] = profile_id
    exercises = client.get("/api/exercises?category=forks").json()
    assert len(exercises) >= 8
    assert all("solution" not in x and "evidence" not in x and "hints" not in x for x in exercises)
    assert client.get("/api/exercises?category=invalid").status_code == 422


def test_solution_hints_progress_and_spaced_repetition(training_client):
    client, sessions = training_client
    item = read_library()[0]
    for level in range(1, 5):
        response = client.post(f"/api/exercises/{item['id']}/hint", json={"level": level})
        assert response.status_code == 200
        assert response.json()["text"] == item["hints"][level - 1]
        if level == 1:
            move = parse_move(chess.Board(item["fen"]), item["solution"][0])
            assert response.json()["highlight_square"] == chess.square_name(move.from_square)
            assert "move" not in response.json()
        else:
            assert response.json()["move"] == item["solution"][0]
    response = client.post(f"/api/exercises/{item['id']}/attempt", json={"moves": item["solution"], "hint_level": 0})
    assert response.status_code == 200, response.text
    assert response.json()["correct"] and response.json()["complete"]
    assert response.json()["hint_level"] == 4  # A client cannot hide server-recorded hints.
    progress = client.get("/api/progress").json()
    assert progress["attempts"] == progress["correct"] == 1
    assert progress["hints_used"] == 4
    assert progress["accuracy"] == 1
    with sessions() as db:
        schedule = db.scalar(select(LearningProgress))
        assert schedule.interval_days == .25
        assert schedule.streak == 0
        assert len(db.scalars(select(ExerciseAttempt)).all()) == 1
    # An independent review increases the repetition interval.
    client.post(f"/api/exercises/{item['id']}/attempt", json={"moves": item["solution"]})
    with sessions() as db:
        schedule = db.scalar(select(LearningProgress))
        assert schedule.streak == 1
        assert schedule.interval_days >= 1


def test_wrong_move_is_retryable_without_solution_spoiler(training_client):
    client, sessions = training_client
    item = read_library()[0]
    board = chess.Board(item["fen"])
    wrong = next(move for move in board.legal_moves if not objective_met(board, move, item["criterion"]))
    response = client.post(f"/api/exercises/{item['id']}/attempt", json={"moves": [wrong.uci()]})
    assert response.status_code == 200
    result = response.json()
    assert not result["correct"] and not result["complete"]
    assert "solution" not in result and result["fen"] == item["fen"]
    with sessions() as db:
        assert db.scalar(select(LearningProgress)).interval_days < .1
    progress = client.get("/api/progress").json()
    assert progress["attempts"] == 1 and progress["accuracy"] == 0
    assert progress["recommendations"][0]["topic"] == "forks"
    assert client.post(f"/api/exercises/{item['id']}/attempt", json={"moves": ["a1a8"]}).status_code == 422


def test_equally_strong_alternative_is_accepted_and_weaker_move_rejected(training_client, monkeypatch):
    client, _ = training_client
    exercise = next(x for x in read_library() if x["id"] == "opening-01")
    def equivalent(board, **kwargs):
        move = kwargs.get("root_moves", [chess.Move.from_uci("e2e4")])[0]
        return {"candidates": [{"uci": move.uci(), "cp": 32 if move.uci() == "e2e4" else 25, "mate": None}]}
    monkeypatch.setattr(training.engine_service, "analyze", equivalent)
    response = client.post(f"/api/exercises/{exercise['id']}/attempt", json={"moves": ["d2d4"]})
    assert response.json()["correct"] and response.json()["complete"]
    assert response.json()["solution"] == ["d2d4"]
    assert "your alternative" in response.json()["explanation"]
    assert response.json()["evidence"]["uci"] == "d2d4"
    def weaker(board, **kwargs):
        return {"candidates": [{"uci": "d2d4", "cp": -150 if kwargs.get("root_moves") else 30, "mate": None}]}
    monkeypatch.setattr(training.engine_service, "analyze", weaker)
    response = client.post(f"/api/exercises/{exercise['id']}/attempt", json={"moves": ["d2d4"]})
    assert not response.json()["correct"]


def test_alternative_requires_live_evidence_but_canonical_works_offline(training_client, monkeypatch):
    client, _ = training_client
    def offline(*args, **kwargs):
        raise EngineUnavailable("offline")
    monkeypatch.setattr(training.engine_service, "analyze", offline)
    assert client.post("/api/exercises/opening-01/attempt", json={"moves": ["d2d4"]}).status_code == 503
    assert client.post("/api/exercises/opening-01/attempt", json={"moves": ["e2e4"]}).json()["correct"]


def test_private_exercises_and_user_progress_are_isolated(training_client):
    client, sessions = training_client
    with sessions() as db:
        owner = db.scalar(select(User))
        data = dict(read_library()[0], id="private-example")
        db.add(Exercise(id=data["id"], category=data["category"], owner_id=owner.id, data=data))
        db.commit()
    assert client.get("/api/exercises/private-example").status_code == 200
    other = client.post("/api/profiles", json={"name": "other-user"})
    assert other.status_code == 201
    client.headers["X-Profile-ID"] = other.json()["id"]
    assert client.get("/api/exercises/private-example").status_code == 404
    assert all(x["id"] != "private-example" for x in client.get("/api/exercises").json())
    assert client.get("/api/progress").json()["attempts"] == 0


def test_daily_session_prioritizes_due_reviews_and_future_mastery_is_delayed(training_client):
    client, sessions = training_client
    with sessions() as db:
        user = db.scalar(select(User))
        db.add(LearningProgress(user_id=user.id, exercise_id="endgame-01", topic="endgame", streak=0,
                                interval_days=.04, due_at=now() - timedelta(days=1)))
        db.add(LearningProgress(user_id=user.id, exercise_id="forks-01", topic="forks", streak=5,
                                interval_days=30, due_at=now() + timedelta(days=30)))
        db.commit()
    session = client.post("/api/training/sessions", json={"kind": "daily", "minutes": 5}).json()
    assert session["exercises"][0]["id"] == "endgame-01"
    assert "forks-01" not in [x["id"] for x in session["exercises"]]
    assert all("solution" not in x for x in session["exercises"])
    only_endgames = client.post("/api/training/sessions", json={"kind": "endgame", "minutes": 10}).json()
    assert all(x["category"] == "endgame" for x in only_endgames["exercises"])


def test_session_link_restores_queue_without_exposing_private_data(training_client):
    client, _ = training_client
    session = client.post("/api/training/sessions", json={"kind": "forks", "minutes": 5}).json()
    response = client.get(f"/api/training/sessions/{session['id']}")
    assert response.status_code == 200
    assert response.json() == session
    assert all("solution" not in item and "evidence" not in item and "hints" not in item
               for item in response.json()["exercises"])
    assert client.get("/api/training/sessions/missing").status_code == 404
    other = client.post("/api/profiles", json={"name": "another learner"}).json()
    client.headers["X-Profile-ID"] = other["id"]
    assert client.get(f"/api/training/sessions/{session['id']}").status_code == 404


def test_multimove_exercise_replies_and_keeps_partial_attempt_unfinished(training_client):
    client, sessions = training_client
    with sessions() as db:
        data = dict(next(x for x in read_library() if x["id"] == "opening-01"),
                    id="opening-sequence", solution=["e2e4", "e7e5", "g1f3"])
        db.add(Exercise(id=data["id"], category="opening", data=data))
        db.commit()
    result = client.post("/api/exercises/opening-sequence/attempt", json={"moves": ["e4"]}).json()
    assert result["correct"] and not result["complete"]
    assert result["reply"] == "e7e5"
    board = chess.Board()
    board.push_san("e4")
    board.push_san("e5")
    assert result["fen"] == board.fen()
    result = client.post("/api/exercises/opening-sequence/attempt", json={"moves": ["e4", "e5", "Nf3"]}).json()
    assert result["correct"] and result["complete"]
    assert client.get("/api/progress").json()["attempts"] == 1


def test_lesson_and_coaching_languages_are_independent(training_client):
    client, sessions = training_client
    with sessions() as db:
        user = db.scalar(select(User))
        user.preferences = {**user.preferences, "language": "da", "coach_language": "en"}
        db.add(HintUsage(user_id=user.id, fen=chess.STARTING_FEN, level=1))
        db.commit()
    lesson = client.get("/api/exercises?category=opening").json()[0]
    assert "Åbning" in lesson["title"]
    hint = client.post("/api/exercises/opening-01/hint", json={"level": 1}).json()
    assert hint["text"].startswith("Scan")
    result = client.post("/api/exercises/opening-01/attempt", json={"moves": ["e4"]}).json()
    assert result["feedback"].startswith("Well spotted")
    progress = client.get("/api/progress").json()
    assert progress["hints_used"] == 2
    assert "øvelse" in progress["recommendations"][0]["reason"]
    with sessions() as db:
        user = db.scalar(select(User))
        user.preferences = {**user.preferences, "coach_language": "da"}
        db.commit()
    hint = client.post("/api/exercises/opening-01/hint", json={"level": 1}).json()
    assert hint["text"].startswith("Undersøg")
    result = client.post("/api/exercises/opening-01/attempt", json={"moves": ["e4"]}).json()
    assert result["feedback"].startswith("Godt set")


@pytest.mark.parametrize("color,moves", [("white", ["e4", "e5", "Nf3", "Nc6"]), ("black", ["d4", "Nf6", "c4", "e6"])])
def test_opening_repertoire_is_legal_persistent_and_owned(training_client, color, moves):
    client, _ = training_client
    response = client.post("/api/repertoire", json={"name": "My opening", "color": color, "moves": moves})
    assert response.status_code == 201, response.text
    line = response.json()
    assert line["color"] == color and line["san"] == moves
    board = chess.Board()
    for san in moves:
        board.push_san(san)
    assert line["fen"] == board.fen()
    assert client.get("/api/repertoire").json()[0]["id"] == line["id"]
    assert client.post("/api/repertoire", json={"name": "Bad", "color": color, "moves": ["e5"]}).status_code == 422
    original_id = client.headers["X-Profile-ID"]
    other = client.post("/api/profiles", json={"name": "new-repertoire-owner"})
    assert other.status_code == 201
    client.headers["X-Profile-ID"] = other.json()["id"]
    assert client.get("/api/repertoire").json() == []
    assert client.delete(f"/api/repertoire/{line['id']}").status_code == 404
    client.headers["X-Profile-ID"] = original_id
    assert client.delete(f"/api/repertoire/{line['id']}").json()["deleted"]
    assert client.get("/api/repertoire").json() == []


def test_wrong_continuation_feedback_uses_the_current_exercise_position(training_client):
    client, _ = training_client
    item = next(x for x in read_library() if x["id"] == "forks-08")
    assert len(item["solution"]) == 3
    result = client.post(f"/api/exercises/{item['id']}/attempt", json={"moves": item["solution"][:1]}).json()
    assert result["correct"] and not result["complete"]
    board = chess.Board(result["fen"])
    wrong = next(move for move in board.legal_moves if not board.is_capture(move))
    response = client.post(f"/api/exercises/{item['id']}/attempt", json={"moves": [*item["solution"][:2], wrong.uci()]}).json()
    assert not response["correct"]
    assert "does not capture" in response["feedback"]
    assert response["fen"] == item["fen"]


_NEW_GOALS = {
    "relative_pin", "exploit_pin", "unpin", "defend", "outpost", "simplify", "repair_pawns",
    "opposition", "hold_corner", "rook_seventh", "finish_development", "fresh_development",
}


@pytest.mark.parametrize("kind", sorted(_NEW_GOALS))
def test_enriched_curriculum_has_observable_objectives_and_rejects_wrong_patterns(kind):
    exercise = next(e for e in read_library() if e["criterion"]["kind"] == kind)
    board = validate_structure(exercise)
    initial = board.fen()
    correct = parse_move(board, exercise["solution"][0])
    assert objective_met(board, correct, exercise["criterion"])
    assert any(not objective_met(board, m, exercise["criterion"]) for m in board.legal_moves)
    assert board.fen() == initial
    assert exercise["description"] and exercise["evidence"]["objective_verified"]


def test_relative_pin_is_legal_to_move_but_exposes_more_valuable_piece():
    from src.backend.exercises import relative_pins
    exercise = next(e for e in read_library() if e["criterion"]["kind"] == "relative_pin")
    board = chess.Board(exercise["fen"])
    color = board.turn
    assert not relative_pins(board, color)
    board.push_uci(exercise["solution"][0])
    front, back = next(iter(relative_pins(board, color)))
    assert board.piece_type_at(front) == chess.KNIGHT and board.piece_type_at(back) == chess.QUEEN
    assert not board.is_pinned(not color, front)  # Relative pins do not make a move illegal.
    escape = next(m for m in board.legal_moves if m.from_square == front)
    board.push(escape)
    assert board.is_attacked_by(color, back)


def test_absolute_pin_exploitation_forbids_apparent_knight_recapture():
    exercise = next(e for e in read_library() if e["criterion"]["kind"] == "exploit_pin")
    board = chess.Board(exercise["fen"])
    color = board.turn
    move = chess.Move.from_uci(exercise["solution"][0])
    knight = next(sq for sq in board.pieces(chess.KNIGHT, not color) if board.is_pinned(not color, sq))
    assert move.to_square in board.attacks(knight)
    board.push(move)
    apparent_recapture = chess.Move(knight, move.to_square)
    assert apparent_recapture in board.pseudo_legal_moves
    assert apparent_recapture not in board.legal_moves


def test_new_lessons_have_public_teaching_introductions_in_both_languages(training_client):
    from src.backend.exercises import localized_exercise, public_exercise
    client, _ = training_client
    for exercise in read_library():
        en = public_exercise(localized_exercise(exercise, "en"))
        da = public_exercise(localized_exercise(exercise, "da"))
        assert len(en["description"]) > 40 and len(da["description"]) > 40
        assert en["description"] != da["description"]
        assert "solution" not in en and "solution" not in da
    query = client.get("/api/exercises?category=pins&language=da").json()
    assert all("description" in item for item in query)
    assert any("relativ binding" in item["description"] for item in query)


def test_center_challenge_requires_pawn_objective_not_just_an_engine_equal_move():
    item = next(e for e in read_library() if e["id"] == "opening-04")
    board = chess.Board(item["fen"])
    assert objective_met(board, board.parse_san("c4"), item["criterion"])
    assert not objective_met(board, board.parse_san("Nf3"), item["criterion"])


def test_continuation_hint_uses_reached_position_and_never_reveals_an_early_move(training_client):
    client, _ = training_client
    item = next(x for x in read_library() if x["id"] == "forks-08")
    prefix = item["solution"][:2]
    first = client.post(f"/api/exercises/{item['id']}/hint", json={"level": 1, "moves": prefix}).json()
    assert "move" not in first
    assert first["highlight_square"] == item["solution"][2][:2]
    second = client.post(f"/api/exercises/{item['id']}/hint", json={"level": 2, "moves": prefix}).json()
    assert second["move"] == item["solution"][2]
    revealed = client.post(f"/api/exercises/{item['id']}/hint", json={"level": 4, "moves": prefix}).json()
    assert revealed["move"] == item["solution"][2]
    invalid = client.post(f"/api/exercises/{item['id']}/hint", json={"level": 1, "moves": ["a1a8"]})
    assert invalid.status_code == 422


def test_retry_success_is_recorded_separately_from_an_independent_solve(training_client):
    client, sessions = training_client
    item = read_library()[0]
    board = chess.Board(item["fen"])
    wrong = next(move for move in board.legal_moves if not objective_met(board, move, item["criterion"]))
    client.post(f"/api/exercises/{item['id']}/attempt", json={"moves": [wrong.uci()]})
    response = client.post(f"/api/exercises/{item['id']}/attempt", json={"moves": item["solution"]})
    assert response.json()["independent"] is False
    with sessions() as db:
        solved = db.scalars(select(ExerciseAttempt).where(ExerciseAttempt.complete.is_(True))).one()
        assert solved.evidence["retry_count"] == 1
        assert db.scalar(select(LearningProgress)).streak == 0
    topic = next(t for t in client.get("/api/progress").json()["topics"] if t["topic"] == item["category"])
    assert topic["independent"] == 0 and topic["mastery"] < topic["accuracy"]


def test_repeated_failures_are_explained_and_prioritized_in_practice(training_client):
    client, _ = training_client
    item = read_library()[0]
    board = chess.Board(item["fen"])
    wrong = next(move for move in board.legal_moves if not objective_met(board, move, item["criterion"]))
    for _ in range(2):
        client.post(f"/api/exercises/{item['id']}/attempt", json={"moves": [wrong.uci()]})
    progress = client.get("/api/progress").json()
    repeated = progress["repeated_mistakes"][0]
    assert repeated["exercise_id"] == item["id"] and repeated["failures"] == 2
    recommendation = progress["recommendations"][0]
    assert recommendation["topic"] == item["category"]
    assert "Repeated" in recommendation["reason"]
    assert "suggested_difficulty" in next(t for t in progress["topics"] if t["topic"] == item["category"])


def test_positional_game_mistakes_create_private_verified_calculation_practice(training_client, monkeypatch):
    from src.backend.models import Game
    client, sessions = training_client
    best = {"uci": "e2e4", "san": "e4", "cp": 30, "mate": None,
            "explanation": "The pawn reaches the center.", "pv_uci": ["e2e4", "e7e5", "g1f3"]}
    monkeypatch.setattr(training.engine_service, "grade", lambda *args, **kwargs: {
        "best": best, "loss_cp": 180, "classification": "Mistake"})
    def continuation(board, **kwargs):
        move = kwargs.get("root_moves", [board.parse_san("e5" if board.turn == chess.BLACK else "Nf3")])[0]
        return {"candidates": [{"uci": move.uci(), "san": board.san(move), "cp": 30, "mate": None, "depth": 12}]}
    monkeypatch.setattr(training.engine_service, "analyze", continuation)
    with sessions() as db:
        user = db.scalar(select(User))
        game = Game(user_id=user.id, initial_fen=chess.STARTING_FEN, player_color="white", moves=[{
            "uci": "a2a3", "san": "a3", "feedback": {"classification": "Mistake"}}])
        db.add(game)
        db.commit()
        game_id = game.id
    response = client.post(f"/api/games/{game_id}/retry", json={"ply": 0})
    assert response.status_code == 200, response.text
    item = response.json()
    assert item["source_game_id"] == game_id and item["move_count"] == 3
    assert "solution" not in item and "e2e4" not in str(item)
    with sessions() as db:
        derived = db.get(Exercise, item["id"])
        assert derived.owner_id == user.id and derived.category == "opening"
        assert derived.data["evidence"]["continuation_checks"][0]["objective_met"]
        assert db.get(Game, game_id).moves[0]["uci"] == "a2a3"
    first = client.post(f"/api/exercises/{item['id']}/attempt", json={"moves": ["e4"]}).json()
    assert first["correct"] and not first["complete"] and first["reply"] == "e7e5"
    retry = client.post(f"/api/games/{game_id}/retry", json={"ply": 0})
    assert retry.status_code == 200 and retry.json()["id"] == item["id"]
    assert client.post(f"/api/games/{game_id}/retry", json={"ply": 1}).status_code == 422
    other = client.post("/api/profiles", json={"name": "other-retry-player"}).json()
    client.headers["X-Profile-ID"] = other["id"]
    assert client.post(f"/api/games/{game_id}/retry", json={"ply": 0}).status_code == 404
