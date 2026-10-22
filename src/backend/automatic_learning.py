"""Durable, bounded automatic analysis using the existing Stockfish grading pipeline.

Game actions are immutable evidence. Analysis rows are retryable outbox entries and
rebuildable projections. No broker or optional language model is required.
"""
import copy
import hashlib
import logging
import threading
from collections import Counter, defaultdict
from datetime import timedelta, timezone
from uuid import uuid4

import chess
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from .auth import current_user
from .database import get_db
from .engine import AnalysisCancelled, engine_service
from .learning_evidence import grade_is_usable, observed_skills, position_key, topic_for, utc_iso
from .learning_models import GameLearningAnalysis, LearningEvent, PlayerLearningState
from .models import Game, GameEvent, User, now
from .schemas import Input, Preferences
from .assistance import CATEGORIES, decision_assistance, record_assistance

log = logging.getLogger(__name__)
router = APIRouter(tags=["Personal learning"])
ANALYSIS_VERSION = 1
WINDOW = 120


def fingerprint(game):
    return hashlib.sha256((game.initial_fen + "|" + " ".join(move["uci"] for move in game.moves)).encode()).hexdigest()


def diary_sync(db, game):
    # The optional integration is imported lazily to keep game/diary modules acyclic.
    from .adaptive_diary import sync_game_diary
    sync_game_diary(db, game)


def ensure_completed(db, game, user=None):
    from .games import completed_result
    if completed_result(game) == "*" or not game.moves or game.mode == "analysis" and game.learning_source != "import":
        if game.completed_at:
            from .adaptive_diary import aware, rebuild_day, user_zone
            user = user or db.get(User, game.user_id)
            old_day = aware(game.completed_at).astimezone(user_zone(user)).date()
            game.completed_at = None
            pending = db.get(GameLearningAnalysis, game.id)
            if pending:
                pending.status, pending.lease_token, pending.lease_until = "cancelled", None, None
            db.flush()
            rebuild_day(db, user, old_day)
            project_profile(db, user)
        return
    user = user or db.get(User, game.user_id)
    if game.completed_at is None: game.completed_at = now()
    if not Preferences.model_validate(user.preferences or {}).automatic_analysis:
        db.flush()
        diary_sync(db, game)
        return
    key = fingerprint(game)
    row = db.get(GameLearningAnalysis, game.id)
    if row is None:
        row = GameLearningAnalysis(game_id=game.id, user_id=game.user_id, fingerprint=key,
            status="queued", evidence={}, version=ANALYSIS_VERSION)
        db.add(row)
    elif row.fingerprint != key or row.version != ANALYSIS_VERSION or row.status == "cancelled":
        row.fingerprint, row.status, row.evidence = key, "queued", {}
        row.attempts, row.next_attempt_at = 0, now()
        row.lease_until, row.lease_token, row.version = None, None, ANALYSIS_VERSION
    db.flush()
    diary_sync(db, game)


def assistance_counts(observations):
    return dict(Counter(item.get("assistance", "unknown") for item in observations))


def game_evidence(game, records):
    from .games import completed_result
    observations = []
    for index, record in enumerate(records):
        if record.get("source") != "player" or record.get("color") != game.player_color:
            # Imported player decisions can inform a qualified history, never independence.
            if record.get("source") != "import" or record.get("color") != game.player_color: continue
        feedback = record.get("feedback") or {}
        if not grade_is_usable(feedback): continue
        try:
            board = chess.Board(record["before_fen"])
            played = chess.Move.from_uci(record["uci"])
            best = chess.Move.from_uci(feedback["best"]["uci"])
            if played not in board.legal_moves or best not in board.legal_moves: continue
            if feedback.get("fen") != board.fen() or feedback["played"].get("uci") != played.uci(): continue
        except (ValueError, KeyError): continue
        assistance = record.get("assistance", {}).get("category", "unknown")
        if record.get("source") == "import": assistance = "unknown"
        skills = sorted(set(observed_skills(board, best, feedback)) | set(observed_skills(board, played, feedback)))
        observations.append({"game_id": game.id, "ply": index + 1, "fen": board.fen(),
            "played_move": played.uci(), "san": record["san"], "alternative": best.uci(),
            "topic": topic_for(board, best), "skills": skills, "classification": feedback["classification"],
            "sound": feedback["classification"] in ("Best", "Excellent", "Good", "Forced"),
            "assistance": assistance, "assistance_events": record.get("assistance", {}).get("event_ids", []),
            "followed_suggestion": record.get("assistance", {}).get("followed_suggestion", False),
            "confidence": feedback["confidence"], "loss_cp": feedback.get("loss_cp"),
            "source": game.learning_source, "opponent_difficulty": game.difficulty,
            "position_complexity": {"pieces": len(board.piece_map()), "legal_moves": board.legal_moves.count()},
            "forced": board.legal_moves.count() == 1, "engine_analysis": feedback})
    eligible = [item for item in observations if item["assistance"] == "independent" and not item["forced"]]
    return {"observations": observations, "counts": assistance_counts(observations),
        "independent_assessed": len(eligible), "independent_sound": sum(item["sound"] for item in eligible),
        "analysis_version": ANALYSIS_VERSION, "engine": "Stockfish", "quick_budget_ms": 250,
        "critical_budget_ms": 5000, "opponent_difficulty": game.difficulty,
        "source": game.learning_source, "completed_at": utc_iso(game.completed_at),
        "result": completed_result(game),
        "completion_reason": game.completion_reason,
        "limitations": ["Observed opportunities only; absence of mistakes does not establish mastery.",
                        "Opponent levels are an internal strength scale, not calibrated Elo."]}


def training_result(db, game, record):
    started = db.scalar(select(GameEvent).where(GameEvent.game_id == game.id,
        GameEvent.kind == "training_started").order_by(GameEvent.created_at).limit(1))
    source = started.payload if started else {}
    feedback = record.get("feedback") or {}
    category = record.get("assistance", {}).get("category", "unknown")
    usable = grade_is_usable(feedback)
    sound = feedback.get("classification") in ("Best", "Excellent", "Good", "Forced") if usable else None
    first = len([move for move in game.moves if move.get("source") == "player"]) == 1
    db.add(LearningEvent(user_id=game.user_id, kind="training_result", topic=source.get("focus", "mixed"),
        fen=record["before_fen"], payload={"game_id": game.id, "revision": game.revision,
            "source": source.get("source"), "reference": source.get("reference"),
            "source_ply": source.get("source_ply"), "played_move": record["uci"], "sound": sound,
            "independent": category == "independent" and not source.get("repetition", 0),
            "assistance": category, "repeated_position": bool(source.get("repetition", 0)),
            "initial_decision": first, "verified": usable, "engine_analysis": feedback}))


def publish_projection(db, game, records, row=None):
    """The same evidence projection is used by automatic and explicit analysis."""
    key = fingerprint(game)
    if row is None:
        row = db.get(GameLearningAnalysis, game.id)
    if row is None:
        row = GameLearningAnalysis(game_id=game.id, user_id=game.user_id, fingerprint=key)
        db.add(row)
    row.fingerprint, row.version = key, ANALYSIS_VERSION
    row.evidence = game_evidence(game, records)
    row.status, row.error, row.lease_until, row.lease_token = "completed", None, None, None
    row.updated_at = now()
    user = db.get(User, game.user_id)
    for item in row.evidence["observations"]:
        event_id = hashlib.sha256(f"{game.id}|{key}|{ANALYSIS_VERSION}|{item['ply']}".encode()).hexdigest()[:36]
        if not db.get(LearningEvent, event_id):
            db.add(LearningEvent(id=event_id, user_id=user.id, kind="game_observation", topic=item["topic"],
                fen=item["fen"], payload={**item, "analysis_version": ANALYSIS_VERSION, "fingerprint": key}))
    db.flush()
    project_profile(db, user)
    diary_sync(db, game)
    return row


def update_manual_learning(db, game):
    """An explicit completed-game review works even when automation is disabled."""
    from .games import completed_result
    if game.mode == "analysis" and game.learning_source != "import" or not game.moves or completed_result(game) == "*": return
    if not all(grade_is_usable(record.get("feedback") or {}) for record in game.moves): return
    if game.completed_at is None: game.completed_at = now()
    publish_projection(db, game, game.moves)
    db.commit()


def initial_profile():
    return {"adaptive_difficulty": 1, "difficulty_reason": "Beginner-friendly starting level; awaiting independent game evidence.",
        "estimated_strength": "internal_level", "sample_games": 0, "independent_assessed": 0,
        "assistance_counts": {}, "concepts": [], "recommendations": [], "adjusted_game_ids": [],
        "limitations": ["Search estimates and observed opportunities; learning outcomes require longitudinal evaluation."]}


def project_profile(db, user):
    # Serialize projections for one user without conflicting with child-row FK key locks.
    db.scalar(select(User).where(User.id == user.id).with_for_update(key_share=True))
    state = db.get(PlayerLearningState, user.id)
    previous = state.data if state else initial_profile()
    rows = db.scalars(select(GameLearningAnalysis).where(GameLearningAnalysis.user_id == user.id,
        GameLearningAnalysis.status == "completed").join(Game, Game.id == GameLearningAnalysis.game_id)
        .order_by(Game.completed_at.desc(), Game.id.desc()).limit(WINDOW)).all()
    rows.reverse()
    by_concept = defaultdict(list)
    counts = Counter()
    for row in rows:
        for item in row.evidence.get("observations", []):
            counts[item["assistance"]] += 1
            if item.get("source") != "game" or item.get("forced"): continue
            for concept in set([item["topic"], *item.get("skills", [])]): by_concept[concept].append(item)
    concepts = []
    for topic, raw in sorted(by_concept.items()):
        # Several decisions in one game and repeated positions cannot establish a trend alone.
        unique = {(item["game_id"], position_key(item["fen"])): item for item in raw}
        samples = list(unique.values())
        independent = [item for item in samples if item["assistance"] == "independent"]
        games = len({item["game_id"] for item in independent})
        rate = sum(item["sound"] for item in independent) / len(independent) if independent else None
        weighted = sum((.94 ** (len(independent) - index - 1)) * item["sound"] for index, item in enumerate(independent))
        weights = sum(.94 ** index for index in range(len(independent)))
        recent_rate = weighted / weights if weights else None
        failures = len({item["game_id"] for item in independent if not item["sound"]})
        status = "insufficient_evidence"
        if len(independent) >= 6 and games >= 3:
            status = "recurring_weakness" if failures >= 3 and recent_rate < .65 else "stable"
            if len(independent) >= 12 and games >= 5 and recent_rate >= .85: status = "consistently_demonstrated_strength"
            midpoint = len(independent) // 2
            old, recent = independent[:midpoint], independent[midpoint:]
            if len({item["game_id"] for item in old}) >= 3 and len({item["game_id"] for item in recent}) >= 3:
                delta = sum(i["sound"] for i in recent) / len(recent) - sum(i["sound"] for i in old) / len(old)
                if delta >= .2: status = "improving"
                elif delta <= -.2: status = "declining"
        elif failures >= 2: status = "emerging_weakness"
        concepts.append({"topic": topic, "status": status, "observations": len(samples), "games": games,
            "independent": len(independent), "independent_success_rate": round(rate, 3) if rate is not None else None,
            "confidence": "moderate" if games >= 5 and len(independent) >= 12 else "limited",
            "evidence": [{key: item[key] for key in ("game_id", "ply", "fen", "san", "classification", "assistance")} for item in samples[-5:]]})
    # An old concern without recent opportunities is unknown, never resolved.
    for historical in previous.get("concepts", []):
        if historical["topic"] not in by_concept:
            concepts.append({**historical, "status": "insufficient_evidence", "confidence": "limited",
                "previous_status": historical.get("previous_status", historical["status"]),
                "historical_observations": historical.get("historical_observations", historical.get("observations", 0)),
                "observations": 0, "games": 0, "independent": 0, "independent_success_rate": None})
    level = previous.get("adaptive_difficulty", 1)
    consumed = set(previous.get("adjusted_game_ids", []))
    eligible = [row for row in rows if row.evidence.get("source") == "game" and row.evidence.get("independent_assessed", 0) >= 8]
    fresh = [row for row in eligible if row.game_id not in consumed]
    reason = previous.get("difficulty_reason", initial_profile()["difficulty_reason"])
    # Four distinct fully analyzed games and at least 32 independent decisions per change.
    # Separate thresholds provide hysteresis; each evidence window is consumed once.
    if len(fresh) >= 4:
        window = fresh[-4:]
        rates = [row.evidence["independent_sound"] / row.evidence["independent_assessed"] for row in window]
        difficulty = [row.evidence.get("opponent_difficulty", 1) for row in window]
        if min(rates) >= .75 and sum(rates) / 4 >= .85 and min(difficulty) >= level and level < 5:
            level += 1
            reason = "Four consistently strong independent games support one higher opponent level."
        elif max(rates) <= .65 and sum(rates) / 4 <= .45 and max(difficulty) <= level and level > 1:
            level -= 1
            reason = "Four consistently difficult independent games support one gentler opponent level."
        else: reason = "Recent independent games support keeping the current challenge steady."
        consumed.update(row.game_id for row in fresh)
    ranked = sorted(concepts, key=lambda item: ({"recurring_weakness": 0, "declining": 1, "emerging_weakness": 2}.get(item["status"], 3), -(item["observations"])))
    recommendations = [{"topic": item["topic"], "reason": item["status"]} for item in ranked if item["status"] in ("recurring_weakness", "declining", "emerging_weakness")][:2]
    if not recommendations: recommendations = [{"topic": "mixed", "reason": "Build evidence through complete games and varied practice."}]
    result = {**initial_profile(), "adaptive_difficulty": level, "difficulty_reason": reason,
        "sample_games": len(rows), "independent_assessed": sum(row.evidence.get("independent_assessed", 0) for row in rows if row.evidence.get("source") == "game"),
        "assistance_counts": dict(counts), "concepts": concepts, "recommendations": recommendations,
        "adjusted_game_ids": [row.game_id for row in rows if row.game_id in consumed], "window_games": WINDOW}
    if state is None:
        state = PlayerLearningState(user_id=user.id)
        db.add(state)
    state.data, state.updated_at = result, now()
    return result


def profile_for(db, user):
    row = db.get(PlayerLearningState, user.id)
    return row.data if row else initial_profile()


def profile_context(db, user):
    """Small auditable history for coaching; explicit complexity remains the user's choice."""
    profile = profile_for(db, user)
    priority = {item["topic"] for item in profile.get("recommendations", [])}
    return {"adaptive_difficulty": profile["adaptive_difficulty"],
        "concepts": [{key: item[key] for key in ("topic", "status", "games", "independent", "confidence")}
            for item in profile.get("concepts", []) if item["topic"] in priority][:2],
        "qualification": "Observed independent game decisions, not a claim about the player's thought process."}


class AutomaticLearning:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None
        self.factory = None

    def start(self, factory):
        self.stop()
        self.factory = factory
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="automatic-learning", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=10)
        self.thread = None

    def run(self):
        while not self.stop_event.is_set():
            try:
                if self.process_one(self.factory): continue
            except Exception:
                log.exception("Automatic learning worker will retry after a database failure")
            self.stop_event.wait(1)

    def process_one(self, factory):
        token = str(uuid4())
        with factory() as db:
            eligible = or_(
                and_(GameLearningAnalysis.status.in_(("queued", "failed")), GameLearningAnalysis.attempts < 3,
                     GameLearningAnalysis.next_attempt_at <= now()),
                and_(GameLearningAnalysis.status == "running", GameLearningAnalysis.lease_until < now()))
            candidate = db.scalar(select(GameLearningAnalysis).where(eligible)
                .order_by(GameLearningAnalysis.next_attempt_at).limit(1))
            if not candidate: return False
            identifier = candidate.game_id
            changed = db.execute(update(GameLearningAnalysis).where(GameLearningAnalysis.game_id == identifier, eligible)
                .values(status="running", lease_token=token, lease_until=now() + timedelta(seconds=180),
                        attempts=GameLearningAnalysis.attempts + 1).execution_options(synchronize_session=False))
            db.commit()
            if changed.rowcount != 1: return True
        try: self.analyze(factory, identifier, token)
        except AnalysisCancelled:
            with factory() as db:
                row = db.get(GameLearningAnalysis, identifier)
                if row and row.lease_token == token:
                    row.status, row.lease_token, row.lease_until = "queued", None, None
                    row.attempts = max(0, row.attempts - 1)
                    db.commit()
        except Exception:
            log.exception("Automatic analysis could not finish game %s", identifier)
            with factory() as db:
                row = db.get(GameLearningAnalysis, identifier)
                if row and row.lease_token == token:
                    row.status, row.error = "failed", "Analysis could not complete; retry is available."
                    row.lease_until, row.lease_token = None, None
                    row.next_attempt_at = now() + timedelta(seconds=min(300, 10 * 2 ** row.attempts))
                    diary_sync(db, db.get(Game, identifier))
                    db.commit()
        return True

    def analyze(self, factory, identifier, token):
        from .games import feedback_for_learner
        with factory() as db:
            row, game = db.get(GameLearningAnalysis, identifier), db.get(Game, identifier)
            if not row or row.lease_token != token or not game: return
            key, records = row.fingerprint, copy.deepcopy(game.moves)
            user = db.get(User, game.user_id)
            preferences = Preferences.model_validate(user.preferences or {})
            if not preferences.automatic_analysis:
                row.status, row.lease_token, row.lease_until = "cancelled", None, None
                db.commit()
                return
            completed_cache = row.evidence.get("feedback_cache", {})
            initial_fen = game.initial_fen
        board = chess.Board(initial_fen)
        for index, record in enumerate(records):
            if self.stop_event.is_set(): raise AnalysisCancelled("Worker stopping")
            move = chess.Move.from_uci(record["uci"])
            feedback = completed_cache.get(str(index)) or record.get("feedback") or {}
            if not grade_is_usable(feedback) or feedback.get("fen") != board.fen():
                feedback = engine_service.grade(board, move, time_ms=250, language=preferences.coach_language,
                    complexity=preferences.complexity, cancel_event=self.stop_event)
            critical = feedback.get("classification") in ("Mistake", "Blunder")
            best_mate, played_mate = feedback.get("best", {}).get("mate"), feedback.get("played", {}).get("mate")
            critical |= best_mate is not None and best_mate > 0 and not (played_mate is not None and played_mate > 0)
            if critical and not feedback.get("critical_verified"):
                feedback = engine_service.grade(board, move, time_ms=5000, mode="deep", language=preferences.coach_language,
                    complexity=preferences.complexity, cancel_event=self.stop_event)
                feedback = {**feedback, "critical_verified": True, "verification_budget_ms": 5000}
            if not grade_is_usable(feedback):
                feedback = engine_service.grade(board, move, time_ms=1000, language=preferences.coach_language,
                    complexity=preferences.complexity, cancel_event=self.stop_event)
            if not grade_is_usable(feedback):
                raise RuntimeError("The engine returned insufficient evidence; retry the game analysis")
            feedback = feedback_for_learner(feedback, "white" if board.turn else "black", game.player_color, preferences.coach_language)
            record["feedback"] = feedback
            completed_cache[str(index)] = feedback
            board.push(move)
            # Release the interactive engine between positions; critical verification
            # uses the existing separate deep worker.
            if self.stop_event.wait(.02): raise AnalysisCancelled("Worker stopping")
            if index % 8 == 7:
                with factory() as db:
                    row = db.get(GameLearningAnalysis, identifier)
                    if row.lease_token != token or row.fingerprint != key: return
                    row.evidence = {"feedback_cache": completed_cache, "completed_plies": index + 1}
                    row.lease_until = now() + timedelta(seconds=180)
                    db.commit()
        with factory() as db:
            row = db.scalar(select(GameLearningAnalysis).where(GameLearningAnalysis.game_id == identifier).with_for_update())
            game = db.scalar(select(Game).where(Game.id == identifier).with_for_update())
            if not row or not game or row.lease_token != token or row.fingerprint != key or fingerprint(game) != key or not game.completed_at: return
            game.moves = records
            game.revision += 1
            db.add(GameEvent(game_id=game.id, revision=game.revision, kind="analysis", payload={
                "automatic": True, "analysis_version": ANALYSIS_VERSION, "fingerprint": key,
                "assessments": [{"ply": index + 1, "feedback": record["feedback"]} for index, record in enumerate(records)]}))
            publish_projection(db, game, records, row)
            db.commit()


automatic_learning = AutomaticLearning()


class AssistanceRequest(Input):
    revision: int = Field(ge=0)
    fen: str = Field(max_length=120)
    category: str = Field(max_length=30)
    source: str = Field(max_length=80)
    suggested_move: str | None = Field(default=None, max_length=5)
    revealed: dict = Field(default_factory=dict)


@router.post("/games/{game_id}/assistance", status_code=201)
def assistance(game_id: str, data: AssistanceRequest, user: User = Depends(current_user), db=Depends(get_db)):
    item = record_assistance(db, user, game_id, data.fen, data.category, data.source,
        data.suggested_move, data.revealed, data.revision)
    if item is None: raise HTTPException(409, "Assistance position does not match this game")
    db.commit()
    return {"id": item.id, **item.payload}


@router.get("/learning/profile")
def learning_profile(user: User = Depends(current_user), db=Depends(get_db)):
    profile = profile_for(db, user)
    if (user.preferences or {}).get("coach_language") == "da":
        reasons = {
            "Beginner-friendly starting level; awaiting independent game evidence.": "Begyndervenligt startniveau; afventer selvstændige beslutninger fra flere partier.",
            "Four consistently strong independent games support one higher opponent level.": "Fire stabilt stærke, selvstændige partier peger på ét højere modstanderniveau.",
            "Four consistently difficult independent games support one gentler opponent level.": "Fire stabilt svære, selvstændige partier peger på ét lettere modstanderniveau.",
            "Recent independent games support keeping the current challenge steady.": "De seneste selvstændige partier peger på at beholde den nuværende udfordring."}
        profile = {**profile, "difficulty_reason": reasons.get(profile["difficulty_reason"], profile["difficulty_reason"])}
    return profile


@router.get("/games/{game_id}/learning")
def learning_status(game_id: str, user: User = Depends(current_user), db=Depends(get_db)):
    from .games import owned_game
    game = owned_game(db, game_id, user)
    row = db.get(GameLearningAnalysis, game.id)
    return {"game_id": game.id, "status": row.status if row else "not_queued", "error": row.error if row else None,
        "completed_at": utc_iso(game.completed_at) if game.completed_at else None,
        "evidence": row.evidence if row and row.status == "completed" else None,
        "attempts": row.attempts if row else 0}


class BackfillRequest(Input):
    after_id: str | None = None
    limit: int = Field(default=50, ge=1, le=100)
    rebuild: bool = False


@router.post("/learning/backfill", status_code=202)
def backfill(data: BackfillRequest, user: User = Depends(current_user), db=Depends(get_db)):
    query = select(Game).where(Game.user_id == user.id, or_(Game.mode != "analysis", Game.learning_source == "import"))
    if data.after_id: query = query.where(Game.id > data.after_id)
    games = db.scalars(query.order_by(Game.id).limit(data.limit + 1)).all()
    selected, queued = games[:data.limit], 0
    for game in selected:
        from .games import completed_result
        if not game.moves or completed_result(game) == "*": continue
        if game.completed_at is None:
            last = db.scalar(select(GameEvent).where(GameEvent.game_id == game.id, GameEvent.kind.in_(("move", "computer_move")))
                .order_by(GameEvent.created_at.desc()).limit(1))
            game.completed_at = last.created_at if last else game.created_at
        existing = db.get(GameLearningAnalysis, game.id)
        if existing and (data.rebuild or existing.status in ("failed", "cancelled")):
            existing.status, existing.attempts, existing.next_attempt_at = "queued", 0, now()
            if data.rebuild: existing.evidence = {}
        ensure_completed(db, game, user)
        queued += 1
    db.commit()
    return {"queued": queued, "next_cursor": selected[-1].id if len(games) > data.limit else None}


@router.post("/games/{game_id}/learning/retry", status_code=202)
def retry_learning(game_id: str, user: User = Depends(current_user), db=Depends(get_db)):
    from .games import completed_result, owned_game
    game = owned_game(db, game_id, user)
    if not game.moves or game.mode == "analysis" and game.learning_source != "import" or completed_result(game) == "*":
        raise HTTPException(409, "Complete a game before requesting automatic learning")
    if not Preferences.model_validate(user.preferences or {}).automatic_analysis:
        raise HTTPException(409, "Enable automatic analysis or use manual game analysis")
    row = db.get(GameLearningAnalysis, game.id)
    if row and row.status in ("running", "completed"):
        return {"game_id": game.id, "status": row.status}
    if row:
        row.status, row.attempts, row.next_attempt_at = "queued", 0, now()
        row.error, row.lease_token, row.lease_until = None, None, None
    ensure_completed(db, game, user)
    db.commit()
    return {"game_id": game.id, "status": "queued"}
