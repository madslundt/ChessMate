"""Real UCI integration checks complement deterministic grading/unit coverage."""
import chess
import chess.engine
import pytest
from sqlalchemy import select

from scripts.validate_exercises import engine_path, verify
from src.backend import training
from src.backend.exercises import CATEGORIES, objective_met, read_library
from src.backend.models import Game, User
from src.backend.training_models import Exercise
from tests.backend.test_training import training_client


@pytest.fixture(scope="module")
def stockfish():
    try:
        path = engine_path()
    except RuntimeError as exc:
        pytest.skip(str(exc))
    with chess.engine.SimpleEngine.popen_uci(path) as engine:
        engine.configure({"Threads": 1, "Hash": 32})
        yield engine


@pytest.mark.parametrize("category", CATEGORIES)
def test_curriculum_sample_objective_and_quality_with_real_stockfish(category, stockfish):
    exercise = next(x for x in read_library() if x["category"] == category)
    evidence = verify(exercise, stockfish, .2)
    assert evidence["objective_verified"] and evidence["pv_uci"]
    assert evidence["depth"] >= 8


def test_real_engine_accepts_another_sound_center_move(training_client, stockfish):
    client, _ = training_client
    result = client.post("/api/exercises/opening-01/attempt", json={"moves": ["d4"]})
    assert result.status_code == 200, result.text
    assert result.json()["correct"] and result.json()["complete"]


def test_game_mistake_conversion_rechecks_evidence_and_preserves_privacy(training_client, stockfish):
    client, sessions = training_client
    seed = next(x for x in read_library() if x["id"] == "forks-01")
    board = chess.Board(seed["fen"])
    wrong = next(m for m in board.legal_moves if board.piece_type_at(m.from_square) == chess.KING)
    after = board.copy()
    after.push(wrong)
    with sessions() as db:
        owner = db.scalar(select(User))
        game = Game(user_id=owner.id, initial_fen=board.fen(), player_color="white" if board.turn else "black",
                    moves=[{"uci": wrong.uci(), "san": board.san(wrong), "fen": after.fen(),
                            "feedback": {"classification": "Blunder", "loss_cp": 99999}}])
        db.add(game)
        db.commit()
        game_id = game.id
    response = client.post(f"/api/games/{game_id}/exercises")
    assert response.status_code == 200, response.text
    assert response.json()["count"] >= 1
    derived = response.json()["exercises"][0]
    assert "solution" not in derived
    with sessions() as db:
        exercise = db.get(Exercise, derived["id"])
        evidence = exercise.data["evidence"]
        assert evidence["loss_cp"] >= 100 and evidence["loss_cp"] != 99999
        assert evidence["source_game_id"] == game_id
        move = chess.Move.from_uci(exercise.data["solution"][0])
        assert objective_met(board, move, exercise.data["criterion"])
    assert client.post(f"/api/games/{game_id}/exercises").json()["count"] == 0


def test_repertoire_practice_creates_verified_private_exercises(training_client, stockfish):
    client, sessions = training_client
    line = client.post("/api/repertoire", json={"name": "Italian", "color": "white", "moves": ["e4", "e5", "Nf3", "Nc6", "Bc4"]}).json()
    practice = client.post(f"/api/repertoire/{line['id']}/practice")
    assert practice.status_code == 200, practice.text
    exercises = practice.json()["exercises"]
    assert len(exercises) == 3
    with sessions() as db:
        for item in exercises:
            assert "solution" not in item
            exercise = db.get(Exercise, item["id"])
            assert exercise.owner_id is not None
            assert exercise.data["evidence"]["objective_verified"]
            assert exercise.data["evidence"]["repertoire_id"] == line["id"]
    assert client.post(f"/api/repertoire/{line['id']}/practice").json()["exercises"] == exercises
    assert client.delete(f"/api/repertoire/{line['id']}").status_code == 200
    assert client.get(f"/api/exercises/{exercises[0]['id']}").status_code == 404


@pytest.mark.parametrize("kind", ["relative_pin", "exploit_pin", "unpin", "outpost", "simplify", "hold_corner", "opposition"])
def test_enriched_concepts_are_sound_with_real_stockfish(kind, stockfish):
    exercise = next(e for e in read_library() if e["criterion"]["kind"] == kind)
    evidence = verify(exercise, stockfish, .3)
    assert evidence["objective_verified"]
    if kind == "hold_corner":
        assert evidence["mate"] is None and abs(evidence["cp"]) <= 20
