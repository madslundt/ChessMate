"""Measure learning reads on isolated SQLite history; never touches a user's database.

Synthetic legal completed games and precomputed analysis exclude Stockfish throughput.
Run with the same Python/host when comparing results. Budgets describe local targets,
not deployment guarantees. Production PostgreSQL and real concurrent engine load must
be measured separately.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chess
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.backend import main
from src.backend.adaptive_diary import digest, empty_statistics, narrative
from src.backend.automatic_learning import automatic_learning, project_profile
from src.backend.database import Base, get_db
from src.backend.diary_models import DailyDiary
from src.backend.learning_models import GameLearningAnalysis
from src.backend.models import Game, User, uid


def corpus():
    board, records = chess.Board(), []
    for index, value in enumerate(("f2f3", "e7e5", "g2g4", "d8h4")):
        move = chess.Move.from_uci(value)
        record = {"uci": value, "san": board.san(move), "before_fen": board.fen(),
            "color": "white" if board.turn else "black", "source": "player" if board.turn else "computer"}
        board.push(move)
        record["fen"] = board.fen()
        records.append(record)
    assert board.is_checkmate()
    return records


def seed(factory, count):
    records = corpus()
    today = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
    days = defaultdict(list)
    with factory() as db:
        user = User(name="benchmark", preferences={"automatic_analysis": False, "timezone": "UTC"})
        db.add(user)
        db.flush()
        owner = user.id
        for index in range(count):
            completed = today - timedelta(days=index // 3, minutes=index % 3)
            game_id = uid()
            observations = [{"game_id": game_id, "ply": ply, "fen": records[ply - 1]["before_fen"],
                "san": records[ply - 1]["san"], "topic": "opening", "skills": ["defense"],
                "classification": "Mistake", "sound": False, "assistance": "independent", "source": "game"}
                for ply in (1, 3)]
            db.add(Game(id=game_id, user_id=owner, initial_fen=chess.STARTING_FEN,
                moves=records, mode="computer", player_color="white", difficulty=1,
                completed_at=completed, created_at=completed, assistance_tracked=True))
            db.flush()
            db.add(GameLearningAnalysis(game_id=game_id, user_id=owner, status="completed", fingerprint=game_id,
                evidence={"observations": observations, "independent_assessed": 2,
                    "independent_sound": 0, "source": "game", "opponent_difficulty": 1}, updated_at=completed))
            days[completed.date()].append((game_id, observations))
        for day, games in days.items():
            stats = empty_statistics()
            stats.update(games=len(games), losses=len(games), independent=2 * len(games), analyzed_games=len(games))
            evidence = {"statistics": stats, "status": "completed", "recommendations": [],
                "observations": [o for _, observations in games for o in observations],
                "games": [{"id": identifier, "analysis_status": "completed"} for identifier, _ in games]}
            db.add(DailyDiary(user_id=owner, date=day, timezone="UTC", status="completed", fingerprint=digest(evidence),
                summary=narrative(evidence), evidence=evidence))
        db.flush()
        project_profile(db, user)
        db.commit()
    return owner


def measure(client, queries, method, path, repeats, budget_ms, data=None):
    elapsed, counts = [], []
    for _ in range(repeats):
        queries[0] = 0
        start = time.perf_counter()
        response = client.request(method, path, json=data) if data is not None else client.request(method, path)
        elapsed.append((time.perf_counter() - start) * 1000)
        counts.append(queries[0])
        if response.status_code not in (200, 201): raise RuntimeError(f"{path}: {response.status_code} {response.text[:200]}")
    tracemalloc.start()
    response = client.request(method, path, json=data) if data is not None else client.request(method, path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {"median_ms": round(statistics.median(elapsed), 2), "max_ms": round(max(elapsed), 2),
        "database_queries": max(counts), "peak_python_mib": round(peak / 1024 ** 2, 2),
        "local_budget_ms": budget_ms, "within_budget": max(elapsed) <= budget_ms}


def main_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 10000])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min(args.sizes) < 1 or args.repeats < 1: parser.error("sizes and repeats must be positive")
    results = []
    for count in args.sizes:
        with tempfile.TemporaryDirectory(prefix="chessmate-learning-benchmark-") as directory:
            engine = create_engine(f"sqlite:///{directory}/history.db", connect_args={"check_same_thread": False})
            Base.metadata.create_all(engine)
            factory = sessionmaker(bind=engine, expire_on_commit=False)
            owner = seed(factory, count)
            def sessions():
                with factory() as db: yield db
            main.app.dependency_overrides[get_db] = sessions
            queries = [0]
            @event.listens_for(engine, "before_cursor_execute")
            def count_queries(*_args): queries[0] += 1
            try:
                with patch.object(main, "SessionLocal", factory), patch.object(main, "engine", engine), \
                        patch.object(automatic_learning, "start", lambda *_: None), patch.object(automatic_learning, "stop", lambda: None):
                    with TestClient(main.app) as client:
                        client.headers["X-Profile-ID"] = owner
                        checks = {
                            "profile": ("GET", "/api/learning/profile", 250, None),
                            "existing_progress": ("GET", "/api/progress", 1000, None),
                            "calendar": ("GET", "/api/diary/calendar?month=2026-10", 250, None),
                            "diary": ("GET", "/api/diary/days/2026-10-22", 500, None),
                            "report_30_days": ("POST", "/api/diary/reports", 2000,
                                {"start_date": "2026-09-23", "end_date": "2026-10-22"}),
                        }
                        metrics = {name: measure(client, queries, method, path, args.repeats, budget, data)
                            for name, (method, path, budget, data) in checks.items()}
                        started = time.perf_counter()
                        with ThreadPoolExecutor(max_workers=4) as pool:
                            responses = list(pool.map(lambda _: client.get("/api/learning/profile"), range(4)))
                        assert all(response.status_code == 200 for response in responses)
                        metrics["four_concurrent_profile_reads_ms"] = round((time.perf_counter() - started) * 1000, 2)
                        results.append({"games": count, "active_days": (count + 2) // 3, "metrics": metrics})
                        print(json.dumps(results[-1]), flush=True)
            finally:
                main.app.dependency_overrides.clear()
                engine.dispose()
    report = {"python": platform.python_version(), "platform": platform.platform(), "database": "isolated temporary SQLite",
        "repeats": args.repeats, "corpus": "Legal four-ply completed games; two precomputed player observations per game; three games per date.",
        "limits": "Read/API projection benchmark only; excludes Stockfish throughput, PostgreSQL, network, and multi-user engine contention.", "results": results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__": main_cli()
