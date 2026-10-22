"""Save text, visual provenance and dialogue progress in one transaction."""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from .coaching_models import CoachingEvidence, CoachingState
from .coaching_state import state_key
from .models import CoachingMessage, User


def persist_response(factory, user_id: str, game_id: str | None, fen: str, question: str, text: str, payload: dict, state: dict,
                     user_message_id: str | None = None) -> dict:
    for attempt in range(3):
        with factory() as db:
            try:
                asked = db.get(CoachingMessage, user_message_id) if user_message_id else None
                if asked is None:
                    asked = CoachingMessage(user_id=user_id, game_id=game_id, fen=fen, role="user", content=question)
                    db.add(asked)
                answer = CoachingMessage(user_id=user_id, game_id=game_id, fen=fen, role="assistant", content=text)
                db.add(answer)
                db.flush()
                if not user_message_id:
                    db.add(CoachingEvidence(message_id=asked.id, payload={"ply": payload.get("ply"), "revision": payload.get("revision")}))
                db.add(CoachingEvidence(message_id=answer.id, payload=payload))
                if game_id:
                    from .assistance import record_assistance
                    # Legal continuations and visual move arrows can reveal a decision
                    # even when the prose avoids spelling out the best move.
                    has_line = bool(payload.get("variations"))
                    has_arrows = any(item.get("arrows") for item in payload.get("insights", []))
                    category = "full_solution" if has_line else "engine_assisted" if has_arrows else "general_guidance"
                    record_assistance(db, db.get(User, user_id), game_id, fen, category, "coach_response",
                        revealed={"message_id": answer.id, "variation_count": len(payload.get("variations", [])),
                                  "evidence_ids": payload.get("evidence_ids", [])})
                key = state_key(user_id, game_id, fen)
                saved = db.get(CoachingState, key)
                if saved:
                    merged = {**state, "discovered_ids": list(dict.fromkeys(saved.data.get("discovered_ids", []) + state.get("discovered_ids", []))),
                              "turns": max(saved.data.get("turns", 0) + 1, state.get("turns", 1))}
                    saved.data = merged
                else:
                    db.add(CoachingState(id=key, user_id=user_id, game_id=game_id, fen=fen, data=state))
                db.commit()
                return {"user_message_id": asked.id, "message_id": answer.id,
                        "user_created_at": asked.created_at.isoformat(), "created_at": answer.created_at.isoformat()}
            except (IntegrityError, StaleDataError):
                db.rollback()
                if attempt == 2: raise RuntimeError("Coaching progress changed concurrently; try again") from None
