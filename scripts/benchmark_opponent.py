"""Compare opponent policies with seeded selections and independent Stockfish scores.

This measures move diversity and search-estimated loss, not an Elo rating.
Run with the same Stockfish binary when comparing reports.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chess
import chess.engine
import src.backend.engine as engine_module


def positions() -> list[dict]:
    fixture = json.loads((ROOT / "tests/fixtures/coaching_benchmark.json").read_text())
    ids = {"opening-03", "opening-06", "middlegame-01", "middlegame-09",
           "endgame-06", "endgame-09", "poisoned-queen", "only-move"}
    after_e4 = chess.Board()
    after_e4.push_uci("e2e4")
    return [{"id": "initial-white", "fen": chess.STARTING_FEN},
            {"id": "initial-black", "fen": after_e4.fen()}] + [
                item for item in fixture["positions"] if item["id"] in ids]


def baseline(service: engine_module.EngineService, board: chess.Board,
             level: int, rng: random.Random) -> chess.Move:
    """The deployed 694f1a1 policy, retained here solely for differential checks."""
    result = service.analyze(board, time_ms={1: 60, 2: 100, 3: 180, 4: 350, 5: 700}[level], candidates=3)
    weights = {1: [1, 1, .8], 2: [1, .7, .5], 3: [1, .35, .15],
               4: [1, .1, .02], 5: [1, 0, 0]}[level]
    candidates = result["candidates"]
    return chess.Move.from_uci(rng.choices(candidates, weights=weights[:len(candidates)])[0]["uci"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=96)
    parser.add_argument("--seed", type=int, default=713)
    parser.add_argument("--reference-ms", type=int, default=1500)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.samples <= 10000 or not 100 <= args.reference_ms <= 10000:
        parser.error("samples must be 1–10000; reference-ms must be 100–10000")
    rows = []
    service = engine_module.EngineService()
    original_random = engine_module.random
    reference = chess.engine.SimpleEngine.popen_uci(service.path())
    reference.configure({"Threads": 1, "Hash": 64})
    reference_id = reference.id
    try:
        for item in positions():
            board = chess.Board(item["fen"])
            reference.configure({"Clear Hash": None})
            evidence = reference.analyse(board, chess.engine.Limit(time=args.reference_ms / 1000),
                                         multipv=board.legal_moves.count())
            scores = {info["pv"][0].uci(): info["score"].pov(board.turn).score(mate_score=100000)
                      for info in evidence if info.get("pv")}
            best = max(scores.values())
            for policy in ("deployed-top-three", "current"):
                for level in range(1, 6):
                    rng = random.Random(args.seed)
                    engine_module.random = rng
                    choices = Counter()
                    for _ in range(args.samples):
                        move = (baseline(service, board, level, rng) if policy == "deployed-top-three"
                                else service.play(board, level))
                        if move not in board.legal_moves:
                            raise AssertionError(f"Illegal choice: {item['id']}/{level}/{move}")
                        choices[move.uci()] += 1
                    missing = choices.keys() - scores.keys()
                    if missing:
                        raise RuntimeError(f"Reference omitted selected moves: {missing}")
                    losses = {move: min(1000, max(0, best - scores[move])) for move in choices}
                    rows.append({"position": item["id"], "policy": policy, "level": level,
                                 "unique_moves": len(choices), "selections": dict(choices),
                                 "mean_loss_cp_capped_1000": round(sum(losses[m] * n for m, n in choices.items()) / args.samples, 1),
                                 "mistake_rate_150cp": round(sum(n for m, n in choices.items() if losses[m] >= 150) / args.samples, 3)})
            print(f"Measured {item['id']}", file=sys.stderr, flush=True)
    finally:
        engine_module.random = original_random
        service.close()
        reference.quit()
    summary = []
    for policy in ("deployed-top-three", "current"):
        for level in range(1, 6):
            subset = [row for row in rows if row["policy"] == policy and row["level"] == level]
            summary.append({"policy": policy, "level": level,
                            "mean_loss_cp_capped_1000": round(sum(r["mean_loss_cp_capped_1000"] for r in subset) / len(subset), 1),
                            "mean_mistake_rate_150cp": round(sum(r["mistake_rate_150cp"] for r in subset) / len(subset), 3)})
    report = {"engine": reference_id, "seed": args.seed, "samples": args.samples,
              "reference_ms": args.reference_ms, "summary": summary, "positions": rows}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
