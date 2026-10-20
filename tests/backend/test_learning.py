from contextlib import contextmanager
from datetime import timedelta

import chess
import pytest
from sqlalchemy import select

from src.backend import main, training
from src.backend.database import get_db
from src.backend.engine import engine_service
from src.backend.exercises import read_library
from src.backend.learning_models import LearningEvent
from src.backend.models import Game, GameEvent, HintUsage, User, now
from src.backend.training_models import Exercise, ExerciseAttempt
from tests.backend.test_training import training_client


def session():
    return contextmanager(main.app.dependency_overrides[get_db])()


def test_calculation_records_first_mistake_hints_accuracy_and_private_mastery(signed, monkeypatch):
    user_id = signed.headers["X-Profile-ID"]
    def grade(board, move, **_kwargs):
        bad = board.turn == chess.BLACK
        return {"classification": "Mistake" if bad else "Good", "confidence": "engine_estimate",
            "text": "Compare the response.", "loss_cp": 160 if bad else 0,
            "best": {"uci": "e7e6" if bad else move.uci(), "cp": 30, "mate": None, "depth": 12},
            "played": {"uci": move.uci(), "cp": -130 if bad else 30, "mate": None, "depth": 12}}
    monkeypatch.setattr(engine_service, "grade", grade)
    monkeypatch.setattr(engine_service, "analyze", lambda board, **_kwargs: {
        "fen": board.fen(), "candidates": [{"cp": 0, "mate": None}]})
    with session() as db:
        db.add(HintUsage(user_id=user_id, fen=chess.STARTING_FEN, level=2))
        db.commit()
    response = signed.post("/api/calculation", json={"fen": chess.STARTING_FEN, "moves": ["e4", "e5", "Nf3"],
        "hint_level": 0, "expected_evaluation": "balanced"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["first_inaccuracy_ply"] == 2 and result["hint_level"] == 2
    assert result["correct"] is False and result["accuracy"] == .667 and not result["independent"]
    with session() as db:
        event = db.get(LearningEvent, result["event_id"])
        assert event.user_id == user_id and event.payload["steps"][1]["role"] == "opponent_response"
        assert "calculation_response" in event.payload["steps"][1]["skills"]
        event.payload = {"correct": True}
        with pytest.raises(ValueError, match="immutable"): db.commit()
        db.rollback()
    progress = signed.get("/api/progress").json()
    assert progress["calculation"]["attempts"] == 1 and progress["calculation"]["response_accuracy"] == 0
    assert next(t for t in progress["topics"] if t["topic"] == "opening")["attempts"] == 1
    assert next(s for s in progress["observed_skills"] if s["skill"] == "calculation_response")["mistakes"] == 1
    history = signed.get("/api/calculation/attempts").json()
    assert history[0]["id"] == result["event_id"] and history[0]["first_inaccuracy_ply"] == 2
    assert signed.get(f"/api/calculation/attempts/{result['event_id']}").status_code == 200
    counters_changed = " ".join(chess.STARTING_FEN.split()[:4] + ["7", "9"])
    retried = signed.post("/api/calculation", json={"fen": counters_changed, "moves": ["e4", "e5", "Nf3"]}).json()
    assert retried["retry_count"] == 1 and retried["hint_level"] == 2
    other = signed.post("/api/profiles", json={"name": "separate-calculation-player"}).json()
    signed.headers["X-Profile-ID"] = other["id"]
    assert signed.get("/api/progress").json()["calculation"]["attempts"] == 0
    assert signed.get("/api/calculation/attempts").json() == []
    assert signed.get(f"/api/calculation/attempts/{result['event_id']}").status_code == 404


def test_transfer_only_matches_later_actual_player_decisions_with_bound_engine_evidence(training_client):
    client, sessions = training_client
    seed = next(item for item in read_library() if item["id"] == "forks-01")
    initial = chess.Board(seed["fen"])
    move = chess.Move.from_uci(seed["solution"][0])
    candidate = {"uci": move.uci(), "cp": 500, "mate": None, "depth": 12}
    feedback = {"fen": initial.fen(), "best": candidate, "played": candidate,
        "classification": "Good", "confidence": "engine_estimate", "loss_cp": 0}
    record = {"before_fen": initial.fen(), "uci": move.uci(), "san": initial.san(move),
        "source": "player", "color": "white", "feedback": feedback}
    with sessions() as db:
        user = db.scalar(select(User))
        db.add(ExerciseAttempt(user_id=user.id, exercise_id=seed["id"], topic="forks", moves=[move.uci()],
            correct=True, complete=True, hint_level=0, evidence={"independent": True}, created_at=now() - timedelta(days=2)))
        actual = Game(user_id=user.id, initial_fen=initial.fen(), player_color="white", mode="computer", moves=[])
        analysis = Game(user_id=user.id, initial_fen=initial.fen(), player_color="white", mode="analysis", moves=[])
        db.add_all([actual, analysis]); db.flush()
        db.add_all([GameEvent(game_id=actual.id, revision=1, kind="move", payload=record, created_at=now() - timedelta(days=3)),
            GameEvent(game_id=actual.id, revision=2, kind="move", payload=record, created_at=now() - timedelta(days=1)),
            GameEvent(game_id=analysis.id, revision=1, kind="move", payload=record, created_at=now() - timedelta(days=1)),
            GameEvent(game_id=actual.id, revision=3, kind="move", payload={**record, "feedback": {**feedback, "confidence": "unstable_search"}}, created_at=now() - timedelta(hours=12))])
        db.commit()
    progress = client.get("/api/progress").json()
    assert progress["transfer"]["decisions"] == progress["transfer"]["sound_decisions"] == 1
    sample = progress["transfer"]["samples"][0]
    assert sample["revision"] == 2 and sample["match"] == "same_position"
    assert sample["evidence"]["best_move"] == move.uci()
    assert "does not establish" in progress["transfer"]["qualification"]


def test_multimove_alternatives_get_private_verified_branches_and_current_hints(training_client, monkeypatch):
    client, sessions = training_client
    seed = next(item for item in read_library() if item["id"] == "opening-01")
    with sessions() as db:
        db.add(Exercise(id="branch-practice", category="opening", data={**seed, "id": "branch-practice",
            "solution": ["e2e4", "e7e5", "g1f3"]}))
        db.commit()
    def analyze(board, **kwargs):
        selected = kwargs.get("root_moves", [None])[0]
        if selected is None:
            selected = board.parse_san("e4" if board.fullmove_number == 1 and board.turn else "d5" if not board.turn else "c4")
        return {"candidates": [{"uci": selected.uci(), "cp": 30, "mate": None, "depth": 12,
            "pv_uci": ["d2d4", "d7d5", "c2c4"] if selected.uci() == "d2d4" else [selected.uci()]}]}
    monkeypatch.setattr(engine_service, "analyze", analyze)
    result = client.post("/api/exercises/branch-practice/attempt", json={"moves": ["d4"]})
    assert result.status_code == 200, result.text
    first = result.json()
    assert first["correct"] and not first["complete"] and first["reply"] == "d7d5"
    hint = client.post("/api/exercises/branch-practice/hint", json={"level": 4,
        "moves": ["d4", "d5"], "branch_id": first["branch_id"]}).json()
    assert hint["move"] == "c2c4"
    solved = client.post("/api/exercises/branch-practice/attempt", json={"moves": ["d4", "d5", "c4"],
        "branch_id": first["branch_id"]}).json()
    assert solved["correct"] and solved["complete"] and solved["solution"] == ["d2d4", "d7d5", "c2c4"]
    assert solved["evidence"]["pv_uci"] == solved["solution"]
    other = client.post("/api/profiles", json={"name": "other-branch-player"}).json()
    client.headers["X-Profile-ID"] = other["id"]
    assert client.post("/api/exercises/branch-practice/hint", json={"level": 1,
        "branch_id": first["branch_id"]}).status_code == 404


def test_defensive_and_pawn_objectives_are_observed_and_mirrored_explanations_use_actual_squares():
    from src.backend.exercises import localized_exercise, objective_met
    from src.backend.learning_evidence import observed_skills
    positions = [("6k1/5ppp/8/8/8/8/qP3PPP/4R1K1 b - - 0 1", "g8f8", "prevent_mate"),
        ("6k1/5ppp/8/8/8/6P1/5P1P/R3r1K1 w - - 0 1", "a1e1", "escape_check"),
        ("7k/7p/PK6/8/8/8/8/8 w - - 0 1", "a6a7", "passed_pawn")]
    for fen, value, kind in positions:
        board = chess.Board(fen); move = chess.Move.from_uci(value)
        assert objective_met(board, move, {"kind": kind})
        if kind != "passed_pawn": assert "defense" in observed_skills(board, move, criterion={"kind": kind})
    seed = next(item for item in read_library() if item["id"] == "middlegame-09")
    mirrored = {**seed, "fen": chess.Board(seed["fen"]).mirror().fen(), "solution": ["a8d8"], "criterion": {"kind": "defend", "target": "d5"}}
    assert "d5" in localized_exercise(mirrored, "da")["explanation"]
    assert "d4" not in localized_exercise(mirrored, "da")["explanation"]


def test_extended_calculation_curriculum_has_every_authored_ply_verified():
    from src.backend.exercises import parse_move, validate_structure
    lessons = [item for item in read_library() if item["id"].startswith("calculation-")]
    assert len(lessons) >= 20
    assert {"prevent_mate", "escape_check", "passed_pawn", "opposition", "hold_corner", "defend", "simplify"} <= {item["criterion"]["kind"] for item in lessons}
    assert {chess.Board(item["fen"]).turn for item in lessons} == {chess.WHITE, chess.BLACK}
    for item in lessons:
        board = validate_structure(item)
        assert 3 <= len(item["solution"]) <= 7
        evidence = item["evidence"]["continuation_evidence"]
        assert len(evidence) == len(item["solution"]) - 1
        board.push(parse_move(board, item["solution"][0]))
        for step in evidence:
            assert step["fen"] == board.fen() and step["depth"] >= 8
            assert step["uci"] == item["solution"][step["ply"] - 1]
            board.push(parse_move(board, step["uci"]))


@pytest.mark.parametrize("level,mastery,length", [("beginner", None, 3), ("intermediate", None, 7), ("advanced", None, 9), ("intermediate", .2, 5), ("beginner", .9, 5)])
def test_personal_continuations_adapt_to_level_and_observed_mastery(level, mastery, length, monkeypatch):
    from src.backend.training_generation import verified_continuation
    line = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "d2d3", "f8c5", "e1g1"]
    def analyze(board, **kwargs):
        move = kwargs.get("root_moves", [chess.Move.from_uci(line[len(board.move_stack)])])[0]
        return {"candidates": [{"uci": move.uci(), "cp": 30, "mate": None, "depth": 14}]}
    monkeypatch.setattr(engine_service, "analyze", analyze)
    solution, evidence = verified_continuation(chess.Board(), {"uci": line[0], "pv_uci": line}, "opening", level, mastery)
    assert solution == line[:length] and len(evidence) == length - 1


def test_personal_tactic_stops_when_its_consequence_is_visible(monkeypatch):
    from src.backend.training_generation import verified_continuation
    seed = next(item for item in read_library() if item["id"] == "forks-01")
    line = seed["evidence"]["pv_uci"]
    def analyze(board, **kwargs):
        move = kwargs.get("root_moves", [chess.Move.from_uci(line[len(board.move_stack)])])[0]
        return {"candidates": [{"uci": move.uci(), "cp": 600, "mate": None, "depth": 14}]}
    monkeypatch.setattr(engine_service, "analyze", analyze)
    solution, _ = verified_continuation(chess.Board(seed["fen"]), {"uci": line[0], "pv_uci": line}, "forks", "advanced")
    assert solution == line[:3]
