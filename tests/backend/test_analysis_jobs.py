import threading
import time
from concurrent.futures import ThreadPoolExecutor

import chess
import pytest
from fastapi import HTTPException

from src.backend.analysis_jobs import AnalysisJobs
from src.backend.engine import AnalysisCancelled, EngineService, engine_service
from src.backend.schemas import PositionRequest, Preferences


def test_bounded_queue_cancellation_and_owner_isolation(monkeypatch):
    manager = AnalysisJobs()
    started = threading.Event()
    def search(board, cancel_event, **kwargs):
        started.set()
        assert cancel_event.wait(3)
        raise AnalysisCancelled("cancelled")
    monkeypatch.setattr(engine_service, "analyze", search)
    prefs = Preferences().model_dump()
    try:
        first = manager.submit("a", PositionRequest(), prefs)
        assert started.wait(1)
        second = manager.submit("a", PositionRequest(), prefs)
        with pytest.raises(HTTPException) as limited: manager.submit("a", PositionRequest(), prefs)
        assert limited.value.status_code == 429
        manager.submit("b", PositionRequest(), prefs)
        manager.submit("b", PositionRequest(), prefs)
        with pytest.raises(HTTPException) as full: manager.submit("c", PositionRequest(), prefs)
        assert full.value.status_code == 429
        with pytest.raises(HTTPException) as other: manager.snapshot("b", first.id)
        assert other.value.status_code == 404
        assert manager.snapshot("a", second.id, cancel=True)["status"] == "cancelled"
        replacement = manager.submit("c", PositionRequest(), prefs)
        assert manager.snapshot("c", replacement.id)["status"] == "queued"
        assert manager.snapshot("a", first.id, cancel=True)["status"] == "cancelled"
        first.future.result(timeout=1)
    finally:
        manager.close()


def test_real_deep_search_stops_promptly_and_engine_remains_usable():
    service = EngineService()
    if not service.path(): pytest.skip("Stockfish not installed")
    cancel = threading.Event()
    started = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(service.analyze, chess.Board(), time_ms=20000, mode="deep", cancel_event=cancel)
            time.sleep(.2)
            cancel.set()
            with pytest.raises(AnalysisCancelled): future.result(timeout=3)
        assert time.monotonic() - started < 3.5
        evidence = service.analyze(chess.Board(), time_ms=50)
        assert evidence["candidates"]
    finally:
        service.close()
