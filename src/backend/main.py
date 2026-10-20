import asyncio
import json
from contextlib import asynccontextmanager

import chess
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import auth, games
from .auth import current_user
from .chess_tools import move_idea, parse_board
from .coach import coach_service
from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .engine import EngineUnavailable, engine_service
from .models import CoachingMessage, HintUsage, PositionAnalysis, User
from .schemas import CoachRequest, HintRequest, PositionRequest, Preferences
from .views import AnalysisView, HintView
from .training import router as training_router, seed_exercises
from .llm_settings import router as llm_settings_router, connection_for


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # PostgreSQL schema changes are owned by Alembic; SQLite is the zero-setup development mode.
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_exercises(db)
    yield
    engine_service.close()


app = FastAPI(title="Chessmate API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "X-Profile-ID"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        origin = request.headers.get("origin")
        same_origin = str(request.base_url).rstrip("/")
        if origin and origin != same_origin and origin not in settings.allowed_origins:
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site" and origin not in settings.allowed_origins:
            return JSONResponse({"detail": "Cross-site request rejected"}, status_code=403)
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > 150000):
            return JSONResponse({"detail": "Request body is too large"}, status_code=413)
        if request.method != "DELETE" and request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"detail": "Send application/json"}, status_code=415)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(EngineUnavailable)
async def engine_error(_request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=503)


api = APIRouter(prefix="/api")
api.include_router(auth.router)
api.include_router(games.router)
api.include_router(training_router)
api.include_router(llm_settings_router)


@api.get("/health", tags=["System"])
def health() -> dict:
    try:
        with engine.connect() as connection:
            from sqlalchemy import text
            connection.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "Database is unavailable") from None
    return {"status": "ok", "engine": "available" if engine_service.path() else "unavailable",
            "llm": "configured" if settings.llm_base_url and settings.llm_model else "offline_fallback"}


@api.get("/settings", tags=["Settings"], response_model=Preferences)
def get_settings(user: User = Depends(current_user)) -> dict:
    return Preferences.model_validate(user.preferences or {}).model_dump()


@api.patch("/settings", tags=["Settings"], response_model=Preferences)
def patch_settings(data: dict, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try: preferences = Preferences.model_validate({**(user.preferences or {}), **data})
    except ValidationError as exc: raise HTTPException(422, json.loads(exc.json())) from exc
    user.preferences = preferences.model_dump()
    db.commit()
    return user.preferences


def position(data: PositionRequest) -> chess.Board:
    try: return parse_board(data.fen, data.moves)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc


@api.post("/analysis", tags=["Analysis"], response_model=AnalysisView)
def analyze(data: PositionRequest, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    board = position(data)
    result = engine_service.analyze(board, time_ms=data.time_ms, depth=data.depth, candidates=data.candidates)
    key = result.get("analysis_key")
    if key and not db.get(PositionAnalysis, key):
        # The database is an audit trail; the bounded in-process cache serves hot requests.
        db.add(PositionAnalysis(key=key, fen=board.fen(), evidence=result))
        try: db.commit()
        except Exception: db.rollback()  # Concurrent duplicate cache insert must not fail analysis.
    language = Preferences.model_validate(user.preferences or {}).coach_language
    for candidate in result["candidates"]:
        candidate["explanation"] = move_idea(candidate["facts"], language)
        if language == "da":
            candidate["risk"] = ("Modstanderen kan lovligt slå den flyttede brik; undersøg hele byttefølgen." if candidate["facts"].get("legal_reply_captures") else
                                 "Undersøg varianten; en kort motorsøgning beviser ikke alle fortsættelser.")
    result["base_fen"] = data.fen
    result["moves"] = data.moves
    return result


@api.post("/hint", tags=["Coaching"], response_model=HintView)
def hint(data: HintRequest, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    board = position(data)
    result = coach_service.hint(board, data.level, data.language, data.time_ms, data.depth, data.candidates)
    db.add(HintUsage(user_id=user.id, fen=board.fen(), level=data.level))
    db.commit()
    return result


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@api.post("/coach", tags=["Coaching"])
def coach(data: CoachRequest, user: User = Depends(current_user), db: Session = Depends(get_db)) -> StreamingResponse:
    board = position(data)
    prefs = Preferences.model_validate(user.preferences or {}).model_dump()
    language = data.language or prefs["coach_language"]
    game_context = {}
    if data.game_id:
        if data.moves and not data.explore:
            raise HTTPException(422, "Hypothetical coaching variations must set explore=true")
        game = games.owned_game(db, data.game_id, user)
        if data.revision is None or data.revision != game.revision:
            raise HTTPException(409, "The game changed; refresh the coaching context")
        positions = [game.initial_fen, *(m["fen"] for m in game.moves)]
        selected_ply = max((i for i, fen in enumerate(positions) if fen == data.fen), default=None)
        if not data.explore and selected_ply is None:
            raise HTTPException(409, "The coaching position does not match this game")
        visible_moves = game.moves[:selected_ply] if selected_ply is not None else []
        # Future actual moves must never contaminate a historical or hypothetical board context.
        player_decisions = [m for m in visible_moves if m.get("feedback") and
                            (game.mode == "analysis" or m.get("color") == game.player_color)]
        last_decision = player_decisions[-1] if player_decisions else None
        assessment_counts = {}
        for decision in player_decisions:
            feedback = decision["feedback"]
            if feedback.get("fen") == decision.get("before_fen"):
                label = feedback.get("classification", "Uncertain")
                assessment_counts[label] = assessment_counts.get(label, 0) + 1
        game_context = {"id": game.id, "revision": game.revision, "mode": game.mode, "player_color": game.player_color,
                        "recent_moves": [{"uci": m["uci"], "san": m["san"], "before_fen": m["before_fen"], "fen": m["fen"]} for m in visible_moves[-12:]],
                        "selected_ply": selected_ply, "hypothetical": data.explore,
                        "last_move": visible_moves[-1] if visible_moves else None,
                        "last_player_decision": last_decision,
                        "assessment_counts": assessment_counts,
                        "actual_game_fen": positions[-1]}
    history = [m.model_dump() for m in data.history[-8:]]
    if not history and data.game_id:
        persisted = db.scalars(select(CoachingMessage).where(CoachingMessage.user_id == user.id,
            CoachingMessage.game_id == data.game_id, CoachingMessage.fen == board.fen())
            .order_by(CoachingMessage.created_at.desc()).limit(8)).all()
        history = [{"role": m.role, "content": m.content} for m in reversed(persisted)]
    user_id = user.id
    llm_connection = connection_for(db, user)

    async def stream():
        yield sse("status", {"source": "analyzing", "fen": board.fen(), "revision": data.revision})
        try:
            context = await asyncio.to_thread(coach_service.context, board, prefs, data.question, history, game_context)
            text, source, fallback_reason = await coach_service.respond(board, context, language, llm=llm_connection)
            # Persist against the exact FEN; no streamed response can update game state.
            def save_messages():
                with SessionLocal() as session:
                    for role, content in (("user", data.question), ("assistant", text)):
                        session.add(CoachingMessage(user_id=user_id, game_id=data.game_id,
                                                    fen=board.fen(), role=role, content=content))
                    session.commit()
            await asyncio.to_thread(save_messages)
            for start in range(0, len(text), 28):
                yield sse("token", {"text": text[start:start + 28], "fen": board.fen()})
                await asyncio.sleep(0)
            yield sse("done", {"text": text, "source": source, "fallback_reason": fallback_reason,
                               "fen": board.fen(), "revision": data.revision})
        except (ValueError, RuntimeError):
            yield sse("error", {"message": "The coaching context could not be verified. Try refreshing this position.", "fen": board.fen()})
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


app.include_router(api)
