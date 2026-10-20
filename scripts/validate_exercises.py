#!/usr/bin/env python3
"""Revalidate original/imported curriculum; optionally write fresh UCI evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chess
import chess.engine
from src.backend.exercises import CATEGORIES, LIBRARY_PATH, parse_move, validate_structure


def engine_path() -> str:
    import os
    path = os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish")
    for fallback in ("/usr/games/stockfish", "/opt/homebrew/opt/stockfish/bin/stockfish"):
        if not path and Path(fallback).is_file():
            path = fallback
    if not path:
        raise RuntimeError("Set STOCKFISH_PATH to an installed Stockfish UCI binary")
    return path


def _sound_scores(top: chess.engine.Score, selected: chess.engine.Score) -> bool:
    tm, sm, tc, sc = top.mate(), selected.mate(), top.score(), selected.score()
    return ((tm is not None and sm is not None and (tm > 0) == (sm > 0))
            or (tc is not None and sc is not None and tc - sc <= 100)
            or (tc is not None and sc is not None and min(tc, sc) >= 1800)
            or (tm is not None and tm > 0 and sc is not None and sc >= 1800)
            or (sm is not None and sm > 0))


def _mixed_losing_scores(top: chess.engine.Score, selected: chess.engine.Score) -> bool:
    """Detect a mate-horizon disagreement, without treating it as equivalence."""
    tm, sm, tc, sc = top.mate(), selected.mate(), top.score(), selected.score()
    return ((tm is not None and tm < 0 and sc is not None and sc <= -900)
            or (sm is not None and sm < 0 and tc is not None and tc <= -900))


def compare_decision(board: chess.Board, move: chess.Move, engine: chess.engine.SimpleEngine,
                     seconds: float) -> tuple[dict, dict, float]:
    """Recheck a failing short search before rejecting an authored solution."""
    budgets = [seconds, max(seconds, 1.5, min(5, seconds * 3))]
    for attempt, budget in enumerate(budgets):
        best = engine.analyse(board, chess.engine.Limit(time=budget))
        chosen = engine.analyse(board, chess.engine.Limit(time=budget), root_moves=[move])
        top, selected = best["score"].pov(board.turn), chosen["score"].pov(board.turn)
        if min(best.get("depth", 0), chosen.get("depth", 0)) >= 8 and _sound_scores(top, selected):
            return best, chosen, budget
        if attempt == 1 and budget <= 5 and _mixed_losing_scores(top, selected):
            # The restricted search can discover a distant forced mate that the
            # preceding unrestricted search has not reached. Reuse its warmed
            # hash for one final pair (at most ten extra seconds). Mixed scores
            # still never pass: the normal depth and equivalence checks apply.
            budgets.append(5.0)
    raise ValueError(f"Unsound or shallow decision {board.san(move)} from {board.fen()}: best={top}, chosen={selected}")


def verify(item: dict[str, Any], engine: chess.engine.SimpleEngine, seconds: float = .2) -> dict:
    board = validate_structure(item)
    move = parse_move(board, item["solution"][0])
    best, chosen, verified_budget = compare_decision(board, move, engine, seconds)
    best_score, chosen_score = best["score"].pov(board.turn), chosen["score"].pov(board.turn)
    bm, cm = best_score.mate(), chosen_score.mate()
    bcp, ccp = best_score.score(), chosen_score.score()
    if item["criterion"]["kind"] in ("fork", "skewer") and ((ccp is not None and ccp < 150) or (cm is not None and cm <= 0)):
        raise ValueError(f"{item['id']}: geometric tactic lacks winning engine evidence")
    if item["criterion"]["kind"] == "hold_corner" and (cm is not None or ccp is None or abs(ccp) > 20):
        raise ValueError(f"{item['id']}: claimed drawing defense is not supported by the engine")
    pv, sans, ucis = board.copy(), [], []
    for step in chosen["pv"][:12]:
        if step not in pv.legal_moves:
            raise ValueError(f"{item['id']}: illegal engine continuation")
        sans.append(pv.san(step))
        ucis.append(step.uci())
        pv.push(step)
    # Every authored continuation must hold up from its own position. Checking
    # only the first move can silently accept a cooperative opponent or a later
    # solver blunder in an otherwise useful multi-move lesson.
    continuation_evidence = []
    continuation = board.copy()
    for index, value in enumerate(item["solution"]):
        step = parse_move(continuation, value)
        if index:
            top, selected, step_budget = compare_decision(continuation, step, engine, seconds)
            depth = min(top.get("depth", 0), selected.get("depth", 0))
            top_score, selected_score = top["score"].pov(continuation.turn), selected["score"].pov(continuation.turn)
            tc, sc, tm, sm = top_score.score(), selected_score.score(), top_score.mate(), selected_score.mate()
            continuation_evidence.append({"ply": index + 1, "fen": continuation.fen(), "uci": step.uci(),
                                          "depth": depth, "budget_seconds": step_budget, "cp": sc, "mate": sm,
                                          "best_cp": tc, "best_mate": tm})
        continuation.push(step)
    return {"engine": engine.id.get("name"), "depth": chosen.get("depth"), "cp": ccp,
            "mate": cm, "best_cp": bcp, "best_mate": bm, "pv_uci": ucis, "pv": sans,
            "budget_seconds": verified_budget, "objective_verified": True,
            "continuation_evidence": continuation_evidence,
            "provenance": item.get("evidence", {}).get("provenance", "Locally imported exercise; engine validated.")}


def validate_library(path: Path, *, write: bool = False, seconds: float = .2,
                     require_curriculum: bool = False) -> list[dict]:
    items = json.loads(path.read_text())
    if not isinstance(items, list) or not items or len(items) > 10000:
        raise ValueError("Expected a nonempty JSON list with at most 10000 exercises")
    ids = [x["id"] for x in items]
    if len(ids) != len(set(ids)):
        raise ValueError("Exercise identifiers must be unique")
    if require_curriculum:
        for category in CATEGORIES:
            if sum(item["category"] == category for item in items) < 8:
                raise ValueError(f"The curriculum needs at least eight {category} exercises")
    with chess.engine.SimpleEngine.popen_uci(engine_path()) as engine:
        engine.configure({"Threads": 1, "Hash": 64})
        for item in items:
            item["evidence"] = verify(item, engine, seconds)
            print(f"Verified {item['id']}: depth {item['evidence']['depth']}")
    if write:
        path.write_text("[\n" + ",\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n]\n")
    return items


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=LIBRARY_PATH)
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--require-curriculum", action="store_true")
    parser.add_argument("--seconds", type=float, default=.2)
    args = parser.parse_args()
    if not .05 <= args.seconds <= 10:
        parser.error("--seconds must be between 0.05 and 10")
    validated = validate_library(args.path, write=args.write_evidence, seconds=args.seconds,
                                 require_curriculum=args.require_curriculum)
    print(f"Validated {len(validated)} exercises with python-chess and Stockfish.")
