"""Cross-boundary privacy and evidence regressions for personalized coaching."""
from contextlib import contextmanager

import chess
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.backend import main
from src.backend.assistance import decision_assistance, record_assistance
from src.backend.database import get_db
from src.backend.learning_models import LearningEvent
from src.backend.models import Game, User


def session():
    return contextmanager(main.app.dependency_overrides[get_db])()


def saved_game(db, user, **kwargs):
    game = Game(user_id=user.id, initial_fen=chess.STARTING_FEN, moves=[],
                mode="computer", assistance_tracked=True, **kwargs)
    db.add(game)
    db.flush()
    return game


def test_assistance_is_position_and_game_owned_and_survives_a_retry(signed):
    """Undo must not turn a previously revealed opening into an independent success."""
    with session() as db:
        user = db.get(User, signed.headers["X-Profile-ID"])
        game = saved_game(db, user)
        other_game = saved_game(db, user)
        disclosure = record_assistance(db, user, game.id, chess.STARTING_FEN,
            "destination_revealed", "hint", suggested_move="e2e4", revision=0)
        db.commit()
        evidence = decision_assistance(db, game, chess.STARTING_FEN, "e2e4")
        assert evidence["category"] == "destination_revealed"
        assert evidence["followed_suggestion"] and evidence["event_ids"] == [disclosure.id]
        assert decision_assistance(db, other_game, chess.STARTING_FEN, "e2e4")["category"] == "independent"
        # A subsequent revision can represent undo followed by revisiting the same decision.
        game.revision = 2
        db.commit()
        retried = decision_assistance(db, game, chess.STARTING_FEN, "d2d4")
        assert retried["category"] == "destination_revealed" and not retried["followed_suggestion"]
        assert db.scalar(select(LearningEvent).where(LearningEvent.id == disclosure.id)) is not None


def test_historical_assistance_omissions_are_unknown_even_for_a_sound_move(signed):
    with session() as db:
        user = db.get(User, signed.headers["X-Profile-ID"])
        legacy = Game(user_id=user.id, initial_fen=chess.STARTING_FEN, moves=[], mode="computer")
        imported = saved_game(db, user, learning_source="import")
        db.add(legacy)
        db.commit()
        for game in (legacy, imported):
            assert decision_assistance(db, game, chess.STARTING_FEN, "e2e4")["category"] == "unknown"


def test_assistance_rejects_foreign_games_stale_revisions_and_unverified_moves(signed):
    with session() as db:
        user = db.get(User, signed.headers["X-Profile-ID"])
        stranger = User(name="foreign-assistance-owner", preferences={})
        db.add(stranger)
        db.flush()
        game = saved_game(db, user)
        foreign = saved_game(db, stranger)
        db.commit()
        for identifier, revision, move, status in (
            (foreign.id, 0, "e2e4", 404),
            (game.id, 9, "e2e4", 409),
            (game.id, 0, "e2e5", 422),
        ):
            with pytest.raises(HTTPException) as rejected:
                record_assistance(db, user, identifier, chess.STARTING_FEN,
                    "full_solution", "coach", suggested_move=move, revision=revision)
            assert rejected.value.status_code == status
        assert db.scalars(select(LearningEvent).where(LearningEvent.kind == "assistance")).all() == []


def test_hypothetical_coaching_does_not_become_a_live_decision(signed):
    with session() as db:
        user = db.get(User, signed.headers["X-Profile-ID"])
        game = saved_game(db, user)
        board = chess.Board()
        board.push_uci("e2e4")
        assert record_assistance(db, user, game.id, board.fen(),
            "engine_assisted", "hypothetical", suggested_move="e7e5") is None
        assert decision_assistance(db, game, chess.STARTING_FEN, "e2e4")["category"] == "independent"
