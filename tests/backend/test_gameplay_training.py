"""Real-game practice must remain a legal normal game, with no forced solution."""
from contextlib import contextmanager

import chess
import pytest
from sqlalchemy import select

from src.backend import main
from src.backend.database import get_db
from src.backend.gameplay_training import real_positions
from src.backend.learning_models import GameLearningAnalysis, LearningEvent
from src.backend.models import Game, GameEvent, User


def session():
    return contextmanager(main.app.dependency_overrides[get_db])()


def test_classic_training_positions_preserve_real_game_complexity():
    positions = real_positions()
    assert len(positions) >= 20
    for item in positions:
        board = chess.Board(item["fen"])
        assert board.is_valid() and not board.is_game_over()
        assert len(board.piece_map()) >= 14
        assert item["reference"] and item["source_ply"] >= 8
    assert any(len(chess.Board(item["fen"]).piece_map()) >= 28 and chess.Board(item["fen"]).legal_moves.count() >= 20 for item in positions)


def test_blind_realistic_training_can_continue_and_diversifies_positions(signed):
    first = signed.post("/api/training/games", json={"focus": "mixed", "blind": True, "minutes": 5})
    assert first.status_code == 201, first.text
    game = first.json()
    assert game["mode"] == "training" and game["learning_source"] == "training"
    assert game["difficulty_mode"] == "adaptive" and game["difficulty"] == 1
    assert len(chess.Board(game["fen"]).piece_map()) >= 14
    assert "topic" not in game and "solution" not in game and "reference" not in game
    before = game["fen"]
    # Any legal decision is accepted, rather than forcing the intended solution.
    move = game["legal_moves"][-1]
    played = signed.post(f"/api/games/{game['id']}/moves", json={"revision": game["revision"], "move": move})
    assert played.status_code == 200, played.text
    game = played.json()
    assert len(game["moves"]) == 1 and game["fen"] != before
    if game["result"] == "*":
        response = signed.post(f"/api/games/{game['id']}/computer", json={"revision": game["revision"]})
        assert response.status_code == 200, response.text
        assert len(response.json()["moves"]) == 2
        board = chess.Board(before)
        for record in response.json()["moves"]:
            assert chess.Move.from_uci(record["uci"]) in board.legal_moves
            board.push_uci(record["uci"])
            assert board.fen() == record["fen"]
    second = signed.post("/api/training/games", json={"focus": "mixed", "blind": True}).json()
    assert second["initial_fen"] != before
    with session() as db:
        source = db.scalar(select(GameEvent).where(GameEvent.game_id == game["id"], GameEvent.kind == "training_started"))
        assert source.payload["fen"] == before
        assert source.payload["repetition"] == 0
        assert db.get(Game, game["id"]).learning_source == "training"


def test_personalized_training_uses_owned_original_position_and_hides_source(signed):
    owner = signed.headers["X-Profile-ID"]
    fen = real_positions()[3]["fen"]
    with session() as db:
        own = Game(user_id=owner, initial_fen=fen, moves=[], mode="computer")
        outsider = User(name="training-outside", preferences={})
        db.add_all([own, outsider])
        db.flush()
        alien = Game(user_id=outsider.id, initial_fen=fen, moves=[], mode="computer")
        db.add(alien)
        db.flush()
        for game in (own, alien):
            db.add(GameLearningAnalysis(game_id=game.id, user_id=game.user_id, fingerprint=game.id, status="completed",
                evidence={"observations": [{"fen": fen, "ply": 12, "topic": "opening", "skills": [], "classification": "Blunder"}]}))
        db.commit()
    response = signed.post("/api/training/games", json={"focus": "development", "blind": True})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["initial_fen"] == fen
    with session() as db:
        started = db.scalar(select(GameEvent).where(GameEvent.game_id == result["id"], GameEvent.kind == "training_started"))
        assert started.payload["reference"] == own.id and started.payload["source_ply"] == 12
    assert alien.id not in str(result) and own.id not in str(result)
    assert signed.post("/api/training/games", json={"focus": "invented"}).status_code == 422


@pytest.mark.parametrize("independent,sound,repeated,expected", [(True, True, False, 3), (False, True, False, 2), (True, True, True, 2), (True, False, False, 1)])
def test_training_difficulty_uses_unfamiliar_initial_decisions_not_continuation_volume(signed, independent, sound, repeated, expected):
    positions = real_positions()
    owner = signed.headers["X-Profile-ID"]
    with session() as db:
        for index in range(6):
            fen = positions[0 if repeated else index]["fen"]
            db.add(LearningEvent(user_id=owner, kind="training_result", topic="mixed", fen=fen,
                payload={"initial_decision": True, "verified": True, "independent": independent, "sound": sound}))
        # Later continuation moves in one session are not new position-selection evidence.
        for _ in range(25):
            db.add(LearningEvent(user_id=owner, kind="training_result", topic="mixed", fen=positions[-1]["fen"],
                payload={"initial_decision": False, "verified": True, "independent": True, "sound": True}))
        db.commit()
    response = signed.post("/api/training/games", json={"focus": "mixed"})
    assert response.status_code == 201, response.text
    with session() as db:
        started = db.scalar(select(GameEvent).where(GameEvent.game_id == response.json()["id"], GameEvent.kind == "training_started"))
        assert started.payload["training_difficulty"] == expected
