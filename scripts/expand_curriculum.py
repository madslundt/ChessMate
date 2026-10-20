#!/usr/bin/env python3
"""Add curated defense, planning and endgame continuations with every ply reverified."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chess
import chess.engine
from scripts.validate_exercises import engine_path, verify
from src.backend.exercises import LIBRARY_PATH, objective_met, parse_move, read_library


def mirror_text(text: str) -> str:
    text = re.sub(r"\b[a-h][1-8]\b", lambda match: chess.square_name(chess.square_mirror(chess.parse_square(match[0]))), text)
    return re.sub(r"\b(White|Black|white|black)\b", lambda match: {"White": "Black", "Black": "White", "white": "black", "black": "white"}[match[0]], text)


def candidates() -> list[dict]:
    sources = {item["id"]: item for item in read_library()}
    selected = []
    for source in ("middlegame-09", "middlegame-10", "middlegame-11", "middlegame-12",
                   "pins-09", "pins-10", "pins-11", "opening-09", "opening-10",
                   "endgame-09", "endgame-10", "endgame-11"):
        item = copy.deepcopy(sources[source])
        item["id"] = f"calculation-{source}"
        item["fen"] = chess.Board(item["fen"]).mirror().fen()
        for key in ("title", "objective", "explanation", "description"):
            if key in item: item[key] = mirror_text(item[key])
        for key in ("target", "corner", "previous_square"):
            if key in item["criterion"]: item["criterion"][key] = mirror_text(item["criterion"][key])
        first = chess.Move.from_uci(item["solution"][0])
        item["solution"] = [chess.Move(chess.square_mirror(first.from_square), chess.square_mirror(first.to_square), promotion=first.promotion).uci()]
        item["tags"] = list(dict.fromkeys(item["tags"] + ["calculation", "multi-move"]))
        selected.append(item)
    authored = [
        ("defend-back-rank", "Remove the back-rank mate threat", "middlegame", "6k1/5ppp/8/8/8/8/qP3PPP/4R1K1 b - - 0 1", "prevent_mate",
         "Stop the immediate mate threat, then calculate the opponent’s reply.",
         "White threatens a back-rank mate with the rook. The first move removes that immediate mate; the continuation also checks the opponent’s strongest resistance."),
        ("answer-rook-check", "Answer the check and activate the rook", "middlegame", "6k1/5ppp/8/8/8/6P1/5P1P/R3r1K1 w - - 0 1", "escape_check",
         "Find a sound answer to the check, then improve the surviving pieces.",
         "The king is in check along the first rank. A legal answer must resolve the check. Calculate the rook’s activity and the opponent’s reply after the immediate danger is removed."),
        ("passed-pawn-race", "Calculate the passed pawn’s advance", "endgame", "7k/7p/PK6/8/8/8/8/8 w - - 0 1", "passed_pawn",
         "Advance the passed pawn and calculate the king’s reply before promotion.",
         "No enemy pawn stands ahead on this pawn’s file or its neighboring file. The king supports its advance. Follow the actual replies rather than assuming that every passed pawn promotes."),
        ("king-route", "Find the king’s route around the defender", "endgame", "8/8/2k5/8/3K4/3P4/8/8 w - - 0 1", "king_activity",
         "Activate the king and calculate the defender’s strongest response.",
         "King activity matters here because a pawn needs support to advance. Calculate the defender’s king moves and compare the remaining pawn position at the end of the shown line."),
    ]
    for identifier, title, category, fen, kind, objective, explanation in authored:
        for mirrored in (False, True):
            board = chess.Board(fen).mirror() if mirrored else chess.Board(fen)
            selected.append({"id": f"calculation-{identifier}" + ("-black" if mirrored else "-white"),
                "title": title + (" · reversed colors" if mirrored else ""), "category": category, "difficulty": 3,
                "fen": board.fen(), "criterion": {"kind": kind}, "solution": [], "objective": objective,
                "explanation": mirror_text(explanation) if mirrored else explanation, "hints": [], "tags": [category, kind, "calculation", "multi-move"]})
    return selected


def expand() -> None:
    items = read_library()
    ids, fens = {item["id"] for item in items}, {" ".join(item["fen"].split()[:4]) for item in items}
    with chess.engine.SimpleEngine.popen_uci(engine_path()) as engine:
        engine.configure({"Threads": 1, "Hash": 64})
        for item in candidates():
            if item["id"] in ids or " ".join(item["fen"].split()[:4]) in fens: continue
            board = chess.Board(item["fen"])
            eligible = [move for move in board.legal_moves if objective_met(board, move, item["criterion"])]
            first = parse_move(board, item["solution"][0]) if item["solution"] else engine.analyse(board, chess.engine.Limit(time=.35), root_moves=eligible)["pv"][0]
            if not objective_met(board, first, item["criterion"]): raise ValueError(f"Unmet authored objective: {item['id']}")
            chosen = engine.analyse(board, chess.engine.Limit(time=.35), root_moves=[first])
            line = [move.uci() for move in chosen["pv"][:7]]
            reached = board.copy()
            for value in line: reached.push_uci(value)
            while len(line) < 3 and not reached.is_game_over(claim_draw=True):
                reply = engine.analyse(reached, chess.engine.Limit(time=.35))["pv"][0]
                line.append(reply.uci()); reached.push(reply)
            if len(line) % 2 == 0: line.pop()
            if len(line) < 3: continue  # A terminal one-move problem does not become a calculation lesson.
            item["solution"] = line
            item["title"] = "Calculate: " + item["title"]
            item["objective"] += " Continue after the opponent’s reply."
            item["difficulty"] = 3 if len(line) <= 5 else 4
            item["hints"] = ["Scan checks, captures and immediate threats.", item["objective"],
                f"Look at the piece on {chess.square_name(first.from_square)}.", f"Try {board.san(first)}."]
            item["evidence"] = {"provenance": "Curated ChessMate calculation lesson; all authored plies rechecked with Stockfish."}
            item["evidence"] = verify(item, engine, .3)
            items.append(item)
            ids.add(item["id"]); fens.add(" ".join(item["fen"].split()[:4]))
            temporary = LIBRARY_PATH.with_suffix(".json.tmp")
            temporary.write_text("[\n" + ",\n".join(json.dumps(row, ensure_ascii=False) for row in items) + "\n]\n")
            temporary.replace(LIBRARY_PATH)
            print(f"Verified {item['id']}: {len(line)} plies", flush=True)
    LIBRARY_PATH.write_text("[\n" + ",\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n]\n")


if __name__ == "__main__": expand()
