"""Owned, bounded deep searches with real UCI stop cancellation."""
import copy
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from .auth import current_user
from .chess_tools import parse_board
from .coaching_strategy import candidate_strategy, strategic_insights
from .engine import AnalysisCancelled, EngineUnavailable, engine_service
from .models import User
from .schemas import PositionRequest, Preferences

router = APIRouter(prefix="/analysis/jobs", tags=["Analysis"])


@dataclass
class AnalysisJob:
    id: str
    owner: str
    fen: str
    status: str = "queued"
    created: float = field(default_factory=time.monotonic)
    cancel: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None
    error: str | None = None
    future: object | None = None
    progress: dict = field(default_factory=dict)


class JobFailed(RuntimeError):
    """A deliberate, safe user-facing worker failure."""


class AnalysisJobs:
    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="deep-analysis")
        self._capacity = threading.BoundedSemaphore(4)
        self._lock = threading.Lock()
        self._jobs = OrderedDict()

    def _prune(self):
        for key, job in list(self._jobs.items()):
            if job.status in ("completed", "cancelled", "failed") and (time.monotonic() - job.created > 600 or len(self._jobs) >= 64):
                self._jobs.pop(key, None)

    def _reserve(self, owner, fen):
        with self._lock:
            self._prune()
            active = sum(job.owner == owner and job.status in ("queued", "running") for job in self._jobs.values())
            if active >= 2 or not self._capacity.acquire(blocking=False):
                raise HTTPException(429, "Deep analysis queue is full; cancel a search or retry shortly")
            job = AnalysisJob(str(uuid4()), owner, fen)
            self._jobs[job.id] = job
            return job

    def set_progress(self, job, **progress):
        with self._lock: job.progress = {**job.progress, **progress}

    def submit_work(self, owner, fen, operation, progress=None):
        job = self._reserve(owner, fen)
        job.progress = progress or {}
        def run():
            try:
                with self._lock:
                    if job.cancel.is_set(): return
                    job.status = "running"
                result = operation(job)
                with self._lock:
                    if job.cancel.is_set(): job.status = "cancelled"
                    else: job.status, job.result = "completed", result
            except AnalysisCancelled:
                with self._lock: job.status = "cancelled"
            except Exception as exc:
                with self._lock:
                    if job.cancel.is_set(): job.status = "cancelled"
                    else:
                        job.status = "failed"
                        job.error = str(exc) if isinstance(exc, JobFailed) else "Analysis could not complete; retry shortly"
        try:
            job.future = self._pool.submit(run)
            job.future.add_done_callback(lambda _future: self._capacity.release())
        except RuntimeError:
            self._capacity.release()
            with self._lock: self._jobs.pop(job.id, None)
            raise HTTPException(503, "Analysis worker is shutting down") from None
        return job

    def submit(self, owner: str, data: PositionRequest, preferences: dict) -> AnalysisJob:
        try: board = parse_board(data.fen, data.moves)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
        job = self._reserve(owner, board.fen())
        def run():
            try:
                with self._lock:
                    if job.cancel.is_set(): return
                    job.status = "running"
                result = engine_service.analyze(board, time_ms=max(5000, data.time_ms), depth=data.depth,
                    candidates=data.candidates, mode="deep", cancel_event=job.cancel)
                if job.cancel.is_set(): raise AnalysisCancelled("Analysis cancelled")
                language = preferences["coach_language"]
                result["strategic_insights"] = strategic_insights(board, board.turn, preferences["complexity"], language)
                for candidate in result["candidates"]:
                    from .chess_tools import move_idea, move_insights
                    candidate["explanation"] = move_idea(candidate["facts"], language)
                    candidate["strategy"] = candidate_strategy(board, candidate, language, preferences["complexity"])
                    candidate["insights"], candidate["variations"] = move_insights(board, candidate, language)
                    candidate["insights"].extend(candidate["strategy"]["effects"])
                result["base_fen"], result["moves"] = data.fen, data.moves
                with self._lock:
                    if not job.cancel.is_set(): job.status, job.result = "completed", result
            except AnalysisCancelled:
                with self._lock: job.status = "cancelled"
            except Exception:
                with self._lock:
                    if job.cancel.is_set(): job.status = "cancelled"
                    else: job.status, job.error = "failed", "Deep analysis could not complete; retry shortly"
        try:
            job.future = self._pool.submit(run)
            job.future.add_done_callback(lambda _future: self._capacity.release())
        except RuntimeError:
            self._capacity.release()
            with self._lock: self._jobs.pop(job.id, None)
            raise HTTPException(503, "Analysis worker is shutting down") from None
        return job

    def snapshot(self, owner: str, identifier: str, cancel=False) -> dict:
        with self._lock:
            job = self._jobs.get(identifier)
            if job is None or job.owner != owner: raise HTTPException(404, "Analysis job not found")
            if cancel and job.status in ("queued", "running"):
                job.cancel.set()
                job.status, job.result = "cancelled", None
                if job.future: job.future.cancel()
            result = {"id": job.id, "status": job.status, "fen": job.fen}
            if job.progress: result["progress"] = copy.deepcopy(job.progress)
            if job.result is not None: result["result"] = copy.deepcopy(job.result)
            if job.error: result["error"] = job.error
            return result

    def close(self):
        self.cancel_all()
        self._pool.shutdown(wait=True, cancel_futures=True)

    def cancel_all(self):
        with self._lock:
            for job in self._jobs.values():
                if job.status in ("queued", "running"):
                    job.cancel.set()
                    job.status = "cancelled"
                    if job.future: job.future.cancel()


analysis_jobs = AnalysisJobs()


@router.post("", status_code=202)
def start_job(data: PositionRequest, user: User = Depends(current_user)) -> dict:
    job = analysis_jobs.submit(user.id, data, Preferences.model_validate(user.preferences or {}).model_dump())
    return analysis_jobs.snapshot(user.id, job.id)


@router.get("/{job_id}")
def job_status(job_id: str, user: User = Depends(current_user)) -> dict:
    return analysis_jobs.snapshot(user.id, job_id)


@router.delete("/{job_id}")
def cancel_job(job_id: str, user: User = Depends(current_user)) -> dict:
    return analysis_jobs.snapshot(user.id, job_id, cancel=True)
