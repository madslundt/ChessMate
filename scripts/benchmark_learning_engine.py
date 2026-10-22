#!/usr/bin/env python3
"""Measure one real automatic game job alongside interactive Stockfish searches.

Uses a disposable database and legal Fool's Mate. This small workload measures
contention and actual verification cost, not general deployment throughput.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chess
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.backend import main  # Registers all model metadata, without running app startup.
from src.backend.automatic_learning import AutomaticLearning, ensure_completed
from src.backend.database import Base
from src.backend.engine import engine_service
from src.backend.gameplay_training import real_positions
from src.backend.learning_models import GameLearningAnalysis
from src.backend.models import Game, User


def interactive(boards):
    durations = []
    for board in boards:
        start = time.perf_counter()
        result = engine_service.analyze(board, time_ms=100, candidates=1)
        durations.append((time.perf_counter() - start) * 1000)
        assert result["candidates"] and chess.Move.from_uci(result["candidates"][0]["uci"]) in board.legal_moves
    return {"requests": len(durations), "median_ms": round(statistics.median(durations), 2),
            "max_ms": round(max(durations), 2), "samples_ms": [round(value, 2) for value in durations]}


def main_benchmark():
    positions = real_positions()
    with tempfile.TemporaryDirectory(prefix="chessmate-engine-benchmark-") as directory:
        engine = create_engine(f"sqlite:///{directory}/bench.db", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            user = User(name="isolated-engine-benchmark", preferences={})
            db.add(user)
            db.flush()
            board, records = chess.Board(), []
            for text in ("f3", "e5", "g4", "Qh4#"):
                move = board.parse_san(text)
                record = {"before_fen": board.fen(), "uci": move.uci(), "san": text,
                    "source": "player" if board.turn else "computer", "color": "white" if board.turn else "black",
                    "assistance": {"category": "independent"}, "feedback": None}
                board.push(move)
                records.append({**record, "fen": board.fen()})
            game = Game(user_id=user.id, initial_fen=chess.STARTING_FEN, moves=records,
                mode="computer", player_color="white", assistance_tracked=True, learning_source="game")
            db.add(game)
            db.flush()
            ensure_completed(db, game, user)
            db.commit()
            identifier = game.id
        # Different positions avoid serving the concurrent sample from the hot cache.
        baseline = interactive([chess.Board(item["fen"]) for item in positions[:6]])
        worker = AutomaticLearning()
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=1) as pool:
            job = pool.submit(worker.process_one, factory)
            concurrent = interactive([chess.Board(item["fen"]) for item in positions[6:12]])
            assert job.result(timeout=180)
        elapsed = time.perf_counter() - started
        with factory() as db:
            analysis = db.get(GameLearningAnalysis, identifier)
            assert analysis.status == "completed", analysis.error
            output = {"workload": "One legal four-ply completed game; fresh Stockfish analysis, 250ms quick / 5000ms critical budgets; six concurrent 100ms interactive requests",
                "baseline_interactive": baseline, "concurrent_interactive": concurrent,
                "background": {"games": 1, "plies": 4, "elapsed_seconds": round(elapsed, 3),
                    "plies_per_second": round(4 / elapsed, 3), "attempts": analysis.attempts,
                    "observations": len(analysis.evidence["observations"])},
                "limitations": "Small local SQLite workload; different baseline/concurrent positions, one background game, no multi-user saturation or production throughput inference."}
        engine.dispose()
    engine_service.close()
    print(json.dumps(output, indent=2))


if __name__ == "__main__": main_benchmark()
