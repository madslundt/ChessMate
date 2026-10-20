#!/usr/bin/env python3
"""Capture comparable coaching outputs; teaching scores require human review."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import chess
from src.backend.coach import CoachService
from src.backend.engine import engine_service
from src.backend.llm_settings import Connection
from src.backend.schemas import Preferences

FIXTURE = ROOT / "tests/fixtures/coaching_benchmark.json"
LEVELS = ("beginner", "intermediate", "advanced")
DIMENSIONS = ("accuracy", "causal_specificity", "opponent_response", "teaching_depth",
              "takeaway", "visual_alignment", "spoiler_discipline")


def load_positions(path: Path = FIXTURE) -> list[dict]:
    positions = json.loads(path.read_text())["positions"]
    if not 30 <= len(positions) <= 50 or len({p["id"] for p in positions}) != len(positions):
        raise ValueError("Expected 30–50 uniquely identified benchmark positions")
    for item in positions:
        board = chess.Board(item["fen"])
        if not board.is_valid(): raise ValueError(f"Invalid benchmark FEN: {item['id']}")
        for value in item["line"]:
            move = chess.Move.from_uci(value)
            if move not in board.legal_moves: raise ValueError(f"Illegal benchmark line: {item['id']}")
            board.push(move)
        if set(item["expected"]) != set(LEVELS):
            raise ValueError(f"Missing teaching level: {item['id']}")
    return positions


def review_summary(rows: list[dict]) -> dict:
    """Missing reviews cannot silently count as passing teaching quality."""
    means, hard_failures, complete = {}, [], bool(rows)
    seen = set()
    for row in rows:
        key = (row["id"], row["level"])
        if key in seen: raise ValueError("Duplicate position/level review")
        seen.add(key)
        if row["level"] not in LEVELS: raise ValueError("Unknown teaching level")
        review = row.get("review") or {}
        scores = review.get("scores") or {}
        hard = review.get("hard_failure")
        if hard is True or row.get("automatic_failures"):
            hard_failures.append(f"{row['id']}/{row['level']}")
        for value in scores.values():
            if type(value) is not int or not 0 <= value <= 2:
                raise ValueError("Review scores must be integers from 0 to 2")
        if set(scores) != set(DIMENSIONS) or type(hard) is not bool:
            complete = False
    for level in LEVELS:
        subset = [row for row in rows if row["level"] == level]
        totals = [sum(row["review"]["scores"].values()) for row in subset
                  if set((row.get("review") or {}).get("scores", {})) == set(DIMENSIONS)]
        means[level] = round(sum(totals) / len(totals), 2) if totals else None
        if not subset or len(totals) != len(subset): complete = False
    return {"review_complete": complete, "means_out_of_14": means,
            "hard_failures": hard_failures,
            "teaching_passed": complete and not hard_failures and all(v is not None and v >= 11 for v in means.values())}


def legal_evidence(analysis: dict, fen: str) -> list[str]:
    failures = []
    if analysis.get("fen") != fen: failures.append("Analysis belongs to another position")
    root = chess.Board(fen)
    if analysis.get("perspective") != ("white" if root.turn else "black"):
        failures.append("Analysis score perspective disagrees with the root position")
    if not root.is_game_over(claim_draw=True) and not analysis.get("candidates"):
        failures.append("No engine evidence for a nonterminal position")
    for candidate in analysis.get("candidates", []):
        board = chess.Board(fen)
        line = candidate.get("pv_uci") or [candidate["uci"]]
        if line[0] != candidate["uci"]: failures.append("Candidate and variation disagree")
        for value in line:
            try:
                move = chess.Move.from_uci(value)
                if move not in board.legal_moves: raise ValueError("Illegal continuation")
                board.push(move)
            except ValueError:
                failures.append("Illegal engine evidence")
                break
    return failures


def visual_failures(visuals: dict, analysis: dict, fen: str) -> list[str]:
    """Check the actual coaching overlays, including positions reached after a move."""
    failures, reachable = [], {fen}
    for candidate in analysis.get("candidates", []):
        board = chess.Board(fen)
        for value in candidate.get("pv_uci") or [candidate["uci"]]:
            try:
                move = board.parse_uci(value)
                board.push(move)
                reachable.add(board.fen())
            except ValueError:
                break
    for variation in visuals.get("variations", []):
        if variation.get("base_fen") != fen:
            failures.append("Visual variation belongs to another position")
            continue
        board = chess.Board(fen)
        try:
            if not any(candidate.get("pv_uci", [])[:len(variation["moves"])] == variation["moves"]
                       for candidate in analysis.get("candidates", [])):
                failures.append("Visual variation lacks supporting engine evidence")
            for value in variation["moves"]:
                board.push(board.parse_uci(value))
            if variation.get("resulting_fen") != board.fen():
                failures.append("Visual variation result disagrees with its moves")
        except (KeyError, ValueError):
            failures.append("Illegal visual variation")
    for insight in visuals.get("insights", []):
        if insight.get("fen") not in reachable:
            failures.append("Visual insight belongs to an unsupported position")
            continue
        board = chess.Board(insight["fen"])
        try:
            for square in insight.get("squares", []): chess.parse_square(square)
            for arrow in insight.get("arrows", []):
                source, target = chess.parse_square(arrow["from"]), chess.parse_square(arrow["to"])
                valid = target in board.attacks(source) if insight.get("claim_type") == "board_geometry" else any(
                    move.from_square == source and move.to_square == target for move in board.legal_moves)
                if not valid: failures.append("Unsupported visual arrow")
        except (KeyError, ValueError):
            failures.append("Invalid visual square")
    return failures


def protected_hint_failures(hints: list[dict], fen: str) -> list[str]:
    failures = []
    if [hint.get("level") for hint in hints] != [1, 2]:
        failures.append("Protected hint capture is incomplete")
    for hint in hints:
        if hint.get("fen") != fen: failures.append("Protected hint belongs to another position")
        if any(hint.get(key) for key in ("candidates", "pv_uci", "insights", "variations", "arrows", "move", "squares")) or (hint.get("level") == 1 and hint.get("highlight_move")):
            failures.append(f"Protected hint {hint.get('level')} exposes move evidence")
        if hint.get("level") == 2 and hint.get("highlight_move"):
            try:
                if chess.Move.from_uci(hint["highlight_move"]) not in chess.Board(fen).legal_moves:
                    raise ValueError("Illegal hint move")
            except ValueError:
                failures.append("Second hint exposes an illegal move arrow")
    return failures


def validate_capture(report: dict) -> list[dict]:
    """A manually scored file must still represent the exact frozen teaching cases."""
    fixture = json.loads(FIXTURE.read_text())
    positions = {position["id"]: position for position in load_positions()}
    rows = report["rows"]
    required = {(identifier, level) for identifier in positions for level in LEVELS}
    if report.get("benchmark_version") != fixture["version"] or {(r["id"], r["level"]) for r in rows} != required:
        raise ValueError("Final review requires every frozen position at all three levels and the current fixture version")
    for row in rows:
        position = positions[row["id"]]
        if (row.get("fen") != position["fen"] or row.get("question") != position["question"]
                or row.get("expected") != position["expected"][row["level"]]):
            raise ValueError("Review case disagrees with its frozen position or teaching expectation")
        analysis = row.get("engine_evidence", {})
        combined = {**analysis, "candidates": analysis.get("candidates", []) + row.get("requested_engine_evidence", [])}
        failures = legal_evidence(combined, position["fen"])
        failures += visual_failures(row.get("visual_evidence", {}), combined, position["fen"])
        failures += protected_hint_failures(row.get("protected_hints", []), position["fen"])
        if not row.get("actual", "").strip(): failures.append("Empty explanation")
        if "visual_evidence" not in row: failures.append("Missing actual visual coaching capture")
        row["automatic_failures"] = list(dict.fromkeys(row.get("automatic_failures", []) + failures))
    return rows


async def capture(args) -> dict:
    positions = load_positions()
    if args.ids:
        requested = set(args.ids.split(","))
        if requested - {p["id"] for p in positions}: raise ValueError("Unknown benchmark id")
        positions = [p for p in positions if p["id"] in requested]
    service, rows = CoachService(), []
    llm = None if args.model else Connection("", "")
    from src.backend.config import settings
    metadata = {"benchmark_version": json.loads(FIXTURE.read_text())["version"],
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "requested_provider": "configured_model" if args.model else "deterministic",
                "model": settings.llm_model if args.model else None, "time_ms": args.time_ms,
                "dimensions": DIMENSIONS, "positions": len(positions)}
    for item in positions:
        board = chess.Board(item["fen"])
        analysis = engine_service.analyze(board, time_ms=args.time_ms)
        for level in LEVELS:
            preferences = Preferences().model_dump()
            preferences.update(complexity=level, show_pv=level != "beginner", hide_best_moves=True,
                               analysis_time_ms=args.time_ms,
                               max_explanation_length={"beginner": 90, "intermediate": 180, "advanced": 300}[level])
            context = service.context(board, preferences, item["question"], [], analysis=analysis)
            started = time.perf_counter()
            text, source, reason = await service.respond(board, context, "en", llm=llm)
            seconds = round(time.perf_counter() - started, 3)
            requested = context.get("requested_candidates", [])
            combined = {**analysis, "candidates": analysis["candidates"] + requested}
            visuals = service.visual_evidence(board, context, "en")
            hints = [service.hint(board, level, time_ms=args.time_ms) for level in (1, 2)]
            failures = legal_evidence(combined, board.fen()) + visual_failures(visuals, combined, board.fen())
            failures += protected_hint_failures(hints, board.fen())
            if not text.strip(): failures.append("Empty explanation")
            rows.append({"id": item["id"], "level": level, "fen": item["fen"],
                         "question": item["question"], "expected": item["expected"][level],
                         "forbidden_claims": item["forbidden_claims"], "actual": text,
                         "source": source, "fallback_reason": reason,
                         "response_seconds": seconds, "word_count": len(text.split()),
                         "engine_evidence": analysis, "requested_engine_evidence": requested,
                         "visual_evidence": visuals, "protected_hints": hints, "preferences": preferences,
                         "automatic_failures": failures,
                         "review": {"scores": {}, "hard_failure": None, "notes": ""}})
            print(f"{item['id']}/{level}: {source}, {seconds:.1f}s" + (f", {reason}" if reason else ""), flush=True)
        print(f"Captured {item['id']} at three levels", flush=True)
        if args.model:
            # Preserve long real-model evaluations even if interrupted; an incomplete
            # capture still cannot pass the full-fixture review gate.
            checkpoint = args.output.with_suffix('.partial.json')
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_text(json.dumps({**metadata, "complete": False, "rows": rows,
                "engine": engine_service._get_engine().id.get("name"), "summary": review_summary(rows)}, ensure_ascii=False, indent=2) + "\n")
    return {**metadata, "complete": True, "engine": engine_service._get_engine().id.get("name"),
            "rows": rows, "summary": review_summary(rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tests/benchmark-results/coaching-benchmark.json")
    parser.add_argument("--model", action="store_true", help="Use configured LLM environment settings; actual source/fallback is recorded")
    parser.add_argument("--time-ms", type=int, default=350)
    parser.add_argument("--ids", help="Comma-separated subset for diagnosis; final gate requires the full fixture")
    parser.add_argument("--review", type=Path, help="Score an edited capture; exits nonzero unless the full benchmark passes")
    args = parser.parse_args()
    if not 50 <= args.time_ms <= 3000: parser.error("--time-ms must be 50–3000")
    try:
        if args.review:
            report = json.loads(args.review.read_text())
            rows = validate_capture(report)
            summary = review_summary(rows)
            print(json.dumps(summary, indent=2))
            return 0 if summary["teaching_passed"] else 1
        report = asyncio.run(capture(args))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        args.output.with_suffix('.partial.json').unlink(missing_ok=True)
        failures = sum(bool(row["automatic_failures"]) for row in report["rows"])
        print(f"Saved {len(report['rows'])} explanations to {args.output}; {failures} automatic failures. Teaching review pending.")
        return 1 if failures else 0
    finally:
        engine_service.close()


if __name__ == "__main__":
    raise SystemExit(main())
