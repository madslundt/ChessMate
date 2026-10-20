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


def verify(item: dict[str, Any], engine: chess.engine.SimpleEngine, seconds: float = .2) -> dict:
    board = validate_structure(item)
    move = parse_move(board, item["solution"][0])
    limit = chess.engine.Limit(time=seconds)
    best = engine.analyse(board, limit)
    chosen = engine.analyse(board, limit, root_moves=[move])
    if min(best.get("depth", 0), chosen.get("depth", 0)) < 8:
        raise ValueError(f"{item['id']}: search too shallow; increase --seconds")
    best_score, chosen_score = best["score"].pov(board.turn), chosen["score"].pov(board.turn)
    bm, cm = best_score.mate(), chosen_score.mate()
    bcp, ccp = best_score.score(), chosen_score.score()
    # A longer mate still achieves a winning objective. Large positive CP is an
    # estimate, so only compare CP with CP rather than pretending mate is CP.
    sound = ((bm is not None and cm is not None and (bm > 0) == (cm > 0))
             or (bcp is not None and ccp is not None and bcp - ccp <= 100)
             or (bm is not None and bm > 0 and ccp is not None and ccp >= 1800)
             or (cm is not None and cm > 0))
    if not sound:
        raise ValueError(f"{item['id']}: intended move not sufficiently sound: best={best_score}, chosen={chosen_score}")
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
    return {"engine": engine.id.get("name"), "depth": chosen.get("depth"), "cp": ccp,
            "mate": cm, "best_cp": bcp, "best_mate": bm, "pv_uci": ucis, "pv": sans,
            "budget_seconds": seconds, "objective_verified": True,
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
