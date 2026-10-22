"""Automatic completion analysis must coexist with an explicit full-game review."""
import threading
import time

from src.backend.engine import engine_service


def test_manual_game_review_waits_for_automatic_deep_verification(signed, monkeypatch):
    automatic_entered = threading.Event()
    errors, calls = [], []
    original = engine_service.grade
    def observed(board, move, **kwargs):
        calls.append(threading.current_thread().name)
        if threading.current_thread().name == "automatic-learning" and kwargs.get("mode") == "deep":
            automatic_entered.set()
        try:
            return original(board, move, **kwargs)
        except Exception as error:
            errors.append((threading.current_thread().name, type(error).__name__, str(error)))
            raise
    monkeypatch.setattr(engine_service, "grade", observed)
    created = signed.post("/api/games", json={"mode": "analysis", "pgn": "1. f3 e5 2. g4 Qh4# 0-1"})
    assert created.status_code == 201, created.text
    game = created.json()
    assert automatic_entered.wait(15), errors
    first = signed.post(f"/api/games/{game['id']}/analysis-jobs", json={"revision": game["revision"]})
    assert first.status_code == 202, first.text
    signed.delete("/api/analysis/jobs/" + first.json()["id"])
    second = signed.post(f"/api/games/{game['id']}/analysis-jobs", json={"revision": game["revision"]})
    assert second.status_code == 202, second.text
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        done = signed.get("/api/analysis/jobs/" + second.json()["id"]).json()
        if done["status"] not in ("queued", "running"): break
        time.sleep(.05)
    assert done["status"] == "completed", (done, errors)
    assert not any(name.startswith("deep-analysis") for name in calls), calls


def test_deep_engine_queue_waits_past_the_interactive_timeout(monkeypatch):
    import chess
    import chess.engine
    from src.backend.engine import EngineService
    service = EngineService(deep_worker=True)
    board = chess.Board()
    class Search:
        multipv = [{"pv": [chess.Move.from_uci("e2e4")], "score": chess.engine.PovScore(chess.engine.Cp(10), chess.WHITE), "depth": 12}]
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def wait(self): return None
    class Engine:
        def analysis(self, *_args, **_kwargs): return Search()
    monkeypatch.setattr(service, "_get_engine", lambda: Engine())
    occupied = threading.Event()
    def earlier_search():
        with service._lock:
            occupied.set()
            time.sleep(2.2)
    holder = threading.Thread(target=earlier_search)
    holder.start()
    assert occupied.wait(1)
    try:
        result = service.analyze(board, time_ms=50, candidates=1, cancel_event=threading.Event())
        assert result["candidates"][0]["uci"] == "e2e4"
    finally:
        holder.join(timeout=3)


def test_cancelling_a_waiting_deep_request_does_not_start_an_engine(monkeypatch):
    import chess
    from src.backend.engine import AnalysisCancelled, EngineService
    service = EngineService(deep_worker=True)
    called = []
    monkeypatch.setattr(service, "_get_engine", lambda: called.append(True))
    cancel = threading.Event()
    errors = []
    def queued_search():
        try: service.analyze(chess.Board(), cancel_event=cancel)
        except Exception as error: errors.append(error)
    service._lock.acquire()
    worker = threading.Thread(target=queued_search)
    worker.start()
    try:
        cancel.set()
        worker.join(timeout=.5)
        assert not worker.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], AnalysisCancelled)
        assert called == []
    finally:
        service._lock.release()
        worker.join(timeout=3)


def test_analysis_only_rebase_preserves_current_assistance_and_rejects_undo_redo(signed):
    from contextlib import contextmanager
    import copy
    import pytest
    from src.backend import main
    from src.backend.analysis_jobs import JobFailed
    from src.backend.database import get_db
    from src.backend.fullgame_analysis import game_signature, persist_assessments
    from src.backend.models import Game, GameEvent
    game = signed.post("/api/games", json={"mode": "analysis", "pgn": "1. e4 *"}).json()
    owner = signed.headers["X-Profile-ID"]
    with contextmanager(main.app.dependency_overrides[get_db])() as db:
        stored = db.get(Game, game["id"])
        signature = game_signature(stored)
        record = copy.deepcopy(stored.moves[0])
        record["assistance"] = {"category": "full_solution", "event_ids": ["new-reveal"]}
        stored.moves, stored.revision = [record], 1
        db.add(GameEvent(game_id=stored.id, revision=1, kind="analysis", payload={}))
        db.commit()
    feedback = {"classification": "Good", "fen": game["initial_fen"]}
    revision = persist_assessments(main.SessionLocal, game["id"], owner, signature, 0,
        [{"ply": 1, "feedback": feedback}], False, {})
    assert revision == 2
    with contextmanager(main.app.dependency_overrides[get_db])() as db:
        stored = db.get(Game, game["id"])
        assert stored.moves[0]["assistance"] == {"category": "full_solution", "event_ids": ["new-reveal"]}
        assert stored.moves[0]["feedback"]["classification"] == "Good"
        # The final UCI sequence can be identical after undo and redo, but the
        # player's opportunity and assistance history changed, so rebasing is unsafe.
        stored.revision = 4
        db.add_all([GameEvent(game_id=stored.id, revision=3, kind="undo", payload={}),
            GameEvent(game_id=stored.id, revision=4, kind="redo", payload={})])
        db.commit()
    with pytest.raises(JobFailed, match="game changed"):
        persist_assessments(main.SessionLocal, game["id"], owner, signature, 2,
            [{"ply": 1, "feedback": feedback}], False, {})


def test_unrecorded_revision_change_cannot_be_rebased(signed):
    from contextlib import contextmanager
    from src.backend import main
    from src.backend.database import get_db
    from src.backend.models import Game
    game = signed.post("/api/games", json={"mode": "analysis", "pgn": "1. e4 *"}).json()
    with contextmanager(main.app.dependency_overrides[get_db])() as db:
        stored = db.get(Game, game["id"])
        stored.revision = 1  # Legacy/unrecorded change has no auditable analysis event.
        db.commit()
    response = signed.post(f"/api/games/{game['id']}/analysis-jobs", json={"revision": 0})
    assert response.status_code == 409


def test_background_engine_queue_wait_has_a_finite_deadline(monkeypatch):
    import chess
    import pytest
    from types import SimpleNamespace
    from src.backend import engine as module
    service = module.EngineService(deep_worker=True)
    clock = iter([0, 31])
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    service._lock.acquire()
    try:
        with pytest.raises(module.EngineUnavailable, match="Deep analysis is busy"):
            service.analyze(chess.Board(), cancel_event=threading.Event())
    finally:
        service._lock.release()


def test_checkpoint_feedback_from_an_old_move_history_is_not_reused(signed):
    from contextlib import contextmanager
    from src.backend import main
    from src.backend.database import get_db
    from src.backend.fullgame_analysis import fresh_analysis_records, game_signature
    from src.backend.learning_models import GameLearningAnalysis
    from src.backend.models import Game
    game = signed.post("/api/games", json={"mode": "analysis", "pgn": "1. d4 *"}).json()
    owner = signed.headers["X-Profile-ID"]
    with contextmanager(main.app.dependency_overrides[get_db])() as db:
        stored = db.get(Game, game["id"])
        signature = game_signature(stored)
        db.add(GameLearningAnalysis(game_id=stored.id, user_id=owner, fingerprint="a-prior-completed-game-history",
            status="cancelled", evidence={"feedback_cache": {"0": {"fen": stored.initial_fen,
                "classification": "Best", "played": {"uci": "e2e4"}, "confidence": "engine_estimate"}}}))
        db.commit()
    records = fresh_analysis_records(main.SessionLocal, game["id"], owner, signature, 0, threading.Event())
    assert records[0]["uci"] == "d2d4" and records[0]["feedback"] is None
