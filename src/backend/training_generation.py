"""Adaptive, freshly checked continuations for personal game exercises."""
import chess

from .engine import engine_service, score_number
from .exercises import parse_move


def verified_continuation(board: chess.Board, candidate: dict, category: str, complexity: str,
                          mastery: float | None = None) -> tuple[list[str], list[dict]]:
    maximum = {"beginner": 3, "intermediate": 7, "advanced": 9}.get(complexity, 3)
    if mastery is not None and mastery < .35: maximum = min(maximum, 5)
    if mastery is not None and mastery >= .8: maximum = min(9, maximum + 2)
    line = candidate.get("pv_uci") or [candidate["uci"]]
    if line[0] != candidate["uci"]: line = [candidate["uci"]]
    position, sequence, evidence = board.copy(stack=False), [], []
    for index, value in enumerate(line[:maximum]):
        try: move = parse_move(position, value)
        except ValueError: break
        if index:
            verified = None
            for budget in (180, 400):
                top = engine_service.analyze(position, candidates=1, time_ms=budget)["candidates"][0]
                selected = (top if top["uci"] == move.uci() else
                    engine_service.analyze(position, candidates=1, time_ms=budget, root_moves=[move])["candidates"][0])
                same_mate = top.get("mate") is not None and selected.get("mate") is not None and (top["mate"] > 0) == (selected["mate"] > 0)
                decisive = top.get("cp") is not None and selected.get("cp") is not None and min(top["cp"], selected["cp"]) >= 1800
                if min(top.get("depth", 0), selected.get("depth", 0)) >= 8 and (same_mate or decisive or score_number(top) - score_number(selected) <= 70):
                    verified = {"ply": index + 1, "fen": position.fen(), "uci": move.uci(),
                        "best": top, "played": selected, "objective_met": True, "budget_ms": budget}
                    break
            if verified is None: break
            evidence.append(verified)
        capture, promotion = position.is_capture(move), bool(move.promotion)
        position.push(move)
        sequence.append(move.uci())
        if position.is_game_over(claim_draw=True): break
        if index >= 2 and index % 2 == 0 and not position.is_check() and (promotion or capture and category in ("forks", "skewers")):
            break  # The tactical consequence is visible; avoid adding irrelevant engine shuffling.
    if len(sequence) % 2 == 0: sequence.pop()
    return sequence or [candidate["uci"]], [item for item in evidence if item["ply"] <= len(sequence)]
