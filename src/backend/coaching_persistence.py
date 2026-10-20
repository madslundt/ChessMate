"""Save text, visual provenance and dialogue progress in one transaction."""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from .coaching_models import CoachingEvidence, CoachingState
from .coaching_state import state_key
from .models import CoachingMessage


def persist_response(factory, user_id: str, game_id: str | None, fen: str, question: str, text: str, payload: dict, state: dict) -> None:
    for attempt in range(3):
        with factory() as db:
            try:
                db.add(CoachingMessage(user_id=user_id, game_id=game_id, fen=fen, role="user", content=question))
                answer = CoachingMessage(user_id=user_id, game_id=game_id, fen=fen, role="assistant", content=text)
                db.add(answer)
                db.flush()
                db.add(CoachingEvidence(message_id=answer.id, payload=payload))
                key = state_key(user_id, game_id, fen)
                saved = db.get(CoachingState, key)
                if saved:
                    merged = {**state, "discovered_ids": list(dict.fromkeys(saved.data.get("discovered_ids", []) + state.get("discovered_ids", []))),
                              "turns": max(saved.data.get("turns", 0) + 1, state.get("turns", 1))}
                    saved.data = merged
                else:
                    db.add(CoachingState(id=key, user_id=user_id, game_id=game_id, fen=fen, data=state))
                db.commit()
                return
            except (IntegrityError, StaleDataError):
                db.rollback()
                if attempt == 2: raise RuntimeError("Coaching progress changed concurrently; try again") from None
