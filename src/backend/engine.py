"""One bounded UCI process. Scores always refer to the root side to move."""
import copy
import hashlib
import math
import random
import shutil
import threading
import time
from collections import OrderedDict
from pathlib import Path

import chess
import chess.engine

from .chess_tools import move_facts, move_idea, observations
from .config import settings


class EngineUnavailable(RuntimeError):
    pass


def score_number(candidate: dict) -> int:
    if candidate.get("mate") is not None:
        mate = candidate["mate"]
        return (100000 - abs(mate)) * (1 if mate > 0 else -1)
    return candidate.get("cp") or 0


def classify_move(best: dict, played: dict, forced: bool = False, depth: int = 0) -> dict:
    """Conservative root comparison, including loss/retention of forced mate."""
    loss = max(0, score_number(best) - score_number(played))
    if forced:
        return {"classification": "Forced", "loss_cp": 0, "confidence": "forced", "win_chance_loss": 0}
    if depth < 8:
        return {"classification": "Uncertain", "loss_cp": loss, "confidence": "limited", "win_chance_loss": None}
    bm, pm = best.get("mate"), played.get("mate")
    if bm and bm > 0 and pm and pm > 0:
        label = "Excellent"  # A longer forced win is not a centipawn blunder.
        loss = 0
    elif bm and bm < 0 and pm and pm < 0:
        label, loss = "Good", 0  # Already forced loss: avoid artificial mate-distance penalties.
    elif pm is not None and pm < 0 and not (bm is not None and bm < 0):
        label = "Blunder"
    elif loss <= 15:
        label = "Best" if best["uci"] == played["uci"] else "Excellent"
    elif loss <= 45: label = "Good"
    elif loss <= 100: label = "Inaccuracy"
    elif loss <= 220: label = "Mistake"
    else: label = "Blunder"
    chance = lambda cp: 1 / (1 + math.exp(-max(-10000, min(10000, cp)) / 350))
    chance_loss = max(0, chance(score_number(best)) - chance(score_number(played)))
    if label in ("Inaccuracy", "Mistake", "Blunder") and pm is None and chance_loss < .03:
        label = "Good"  # Large CP changes in already decisive positions need not change the outcome.
    return {"classification": label, "loss_cp": loss, "confidence": "engine_estimate",
            "win_chance_loss": round(chance_loss, 3)}


class EngineService:
    def __init__(self):
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._last_failure = 0.0

    def path(self) -> str | None:
        return settings.stockfish_path or shutil.which("stockfish") or next((p for p in (
            "/usr/games/stockfish", "/usr/bin/stockfish", "/opt/homebrew/bin/stockfish",
            "/opt/homebrew/opt/stockfish/bin/stockfish") if Path(p).is_file()), None)

    def _get_engine(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            path = self.path()
            if not path or time.monotonic() - self._last_failure < 3:
                raise EngineUnavailable("Stockfish is unavailable. Configure STOCKFISH_PATH.")
            try:
                self._engine = chess.engine.SimpleEngine.popen_uci(path, timeout=8)
                self._engine.configure({"Threads": settings.engine_threads, "Hash": settings.engine_hash_mb})
            except (OSError, chess.engine.EngineError, TimeoutError) as exc:
                if self._engine:
                    self._engine.close()
                    self._engine = None
                self._last_failure = time.monotonic()
                raise EngineUnavailable("Stockfish could not start") from exc
        return self._engine

    @staticmethod
    def observations(board: chess.Board) -> dict:
        return observations(board)

    def close(self) -> None:
        with self._lock:
            if self._engine:
                try: self._engine.quit()
                except (chess.engine.EngineError, TimeoutError): self._engine.close()
                self._engine = None

    def analyze(self, board: chess.Board, time_ms: int = 250, depth: int | None = None,
                candidates: int = 3, root_moves: list[chess.Move] | None = None) -> dict:
        if not board.is_valid(): raise ValueError("Invalid chess position")
        if root_moves and any(move not in board.legal_moves for move in root_moves):
            raise ValueError("Illegal root move")
        time_ms = max(50, min(3000, time_ms))
        candidates = max(1, min(3, candidates))
        depth = max(1, min(24, depth)) if depth else None
        key = hashlib.sha256(repr((board.fen(), [m.uci() for m in board.move_stack], time_ms, depth,
                                    candidates, [m.uci() for m in root_moves] if root_moves else None)).encode()).hexdigest()
        result = {"fen": board.fen(), "perspective": "white" if board.turn else "black",
                  "candidates": [], "observations": observations(board), "source": "stockfish"}
        if board.is_game_over(claim_draw=True):
            result["terminal"] = board.outcome(claim_draw=True).termination.name.lower()
            return result
        # A finite queue avoids unlimited worker backlog when many requests arrive.
        if not self._lock.acquire(timeout=12): raise EngineUnavailable("Engine is busy; retry shortly")
        try:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < 600:
                self._cache.move_to_end(key)
                return copy.deepcopy(cached[1])
            engine = self._get_engine()
            try:
                infos = engine.analyse(board, chess.engine.Limit(time=time_ms / 1000, depth=depth),
                                       multipv=min(candidates, len(root_moves) if root_moves else board.legal_moves.count()),
                                       root_moves=root_moves)
            except (chess.engine.EngineError, TimeoutError, OSError) as exc:
                engine.close()
                self._engine = None
                self._last_failure = time.monotonic()
                raise EngineUnavailable("Stockfish analysis failed; retry shortly") from exc
            for info in infos:
                pv = info.get("pv", [])
                if not pv: continue
                variation, san_pv, uci_pv = board.copy(), [], []
                for move in pv[:10]:
                    if move not in variation.legal_moves: break
                    san_pv.append(variation.san(move))
                    uci_pv.append(move.uci())
                    variation.push(move)
                score = info["score"].pov(board.turn)
                facts = move_facts(board, pv[0])
                result["candidates"].append({"uci": pv[0].uci(), "san": board.san(pv[0]),
                    "cp": score.score(), "mate": score.mate(), "white_cp": info["score"].white().score(),
                    "white_mate": info["score"].white().mate(), "pv": san_pv, "pv_uci": uci_pv,
                    "depth": info.get("depth", 0), "facts": facts, "explanation": move_idea(facts),
                    "reply": san_pv[1] if len(san_pv) > 1 else None,
                    "risk": "Check the principal variation; a search estimate is not a proof of every continuation."})
            if result["candidates"]:
                best = result["candidates"][0]
                for candidate in result["candidates"]:
                    candidate["difference_cp"] = max(0, score_number(best) - score_number(candidate))
                    candidate["similar_to_best"] = candidate["difference_cp"] <= 35
                    if candidate["facts"].get("legal_reply_captures"):
                        candidate["risk"] = "The opponent can legally capture the moved piece; evaluate the exchange rather than assuming it is safe."
            result["analysis_key"] = key
            self._cache[key] = (time.monotonic(), copy.deepcopy(result))
            while len(self._cache) > 256: self._cache.popitem(last=False)
            return result
        finally:
            self._lock.release()

    def grade(self, board: chess.Board, move: chess.Move, time_ms: int = 250, language: str = "en") -> dict:
        # Both searches begin at the identical root, share a time/depth budget, and use root POV.
        # One full root search followed by a constrained root search avoids opponent-POV mistakes.
        alternatives = self.analyze(board, time_ms=time_ms, candidates=3)
        if not alternatives["candidates"]: raise ValueError("Game already over")
        played = self.analyze(board, time_ms=time_ms, candidates=1, root_moves=[move])["candidates"][0]
        best = alternatives["candidates"][0]
        effective_depth = min(best["depth"], played["depth"])
        assessment = classify_move(best, played, board.legal_moves.count() == 1, effective_depth)
        # Independent short searches are noisy. A large disagreement on an identical move is never a blunder.
        if best["uci"] == move.uci() and effective_depth >= 8:
            assessment.update(classification="Best", loss_cp=0, win_chance_loss=0)
        facts = move_facts(board, move)
        labels = {"Best": "Bedste træk", "Excellent": "Fremragende", "Good": "Godt træk", "Inaccuracy": "Unøjagtighed",
                  "Mistake": "Fejl", "Blunder": "Alvorlig fejl", "Forced": "Tvunget træk", "Uncertain": "Usikker vurdering"}
        label = labels.get(assessment["classification"]) if language == "da" else assessment["classification"]
        text = f"{label}. {move_idea(facts, language)}"
        if assessment["classification"] in ("Best", "Excellent", "Good") and facts["capture"]:
            captured_piece = facts.get("captured_piece") or "pawn"
            if language == "da":
                captured_piece = {"pawn": "bonde", "knight": "springer", "bishop": "løber", "rook": "tårn", "queen": "dronning"}.get(captured_piece, "brik")
            difference = assessment["loss_cp"] / 100
            if language == "da":
                if facts.get("legal_reply_captures"):
                    explanation = (f"Du slår en {captured_piece}, og selv efter {facts['legal_reply_captures'][0]} "
                                   f"vurderer motoren trækket kun {difference:.1f} bonde under sit bedste valg.")
                else:
                    explanation = (f"Du slår en {captured_piece}, som ikke straks kan slås tilbage på {facts['to']}; "
                                   f"du vinder materiale, mens trækket holder sig {difference:.1f} bonde fra motorens bedste valg.")
            elif facts.get("legal_reply_captures"):
                explanation = (f"You take a {captured_piece}; even after {facts['legal_reply_captures'][0]}, "
                               f"the engine rates the move only {difference:.1f} pawns below its top choice.")
            else:
                explanation = (f"You take a {captured_piece} with no immediate legal recapture on {facts['to']}, "
                               f"so the material gain holds while the move stays {difference:.1f} pawns from the engine's top choice.")
            text = f"{label}. {explanation}"
        after = board.copy()
        after.push(move)
        resulting = observations(after)
        own = "white" if board.turn else "black"
        exposed = [p for p in resulting["exposed_pieces"] if p["color"] == own]
        consequence = ""
        if assessment["classification"] in ("Mistake", "Blunder", "Inaccuracy"):
            if played.get("mate") is not None and played["mate"] < 0:
                consequence = ("Motoren finder en tvungen mat mod dig." if language == "da" else
                               "The engine finds a forced mate against you.")
            elif exposed:
                squares = ", ".join(p["square"] for p in exposed[:2])
                consequence = (f"Efter trækket er dine brikker på {squares} angrebet og udækkede. Undersøg slagene." if language == "da" else
                               f"After this move, your pieces on {squares} are attacked and undefended. Check the possible captures.")
            elif facts.get("legal_reply_captures"):
                consequence = (f"Modstanderen kan lovligt slå din brik på {facts['to']}. Undersøg hele byttefølgen." if language == "da" else
                               f"The opponent has a legal capture of the moved piece on {facts['to']}. Examine the full exchange.")
                loss = assessment["loss_cp"] / 100
                consequence += (f" Det er derfor trækket ligger cirka {loss:.1f} bonde under {best['san']}." if language == "da" else
                                f" This leaves the move about {loss:.1f} pawns below {best['san']}.")
            else:
                reply = played.get("pv", [])[1] if len(played.get("pv", [])) > 1 else None
                loss = assessment["loss_cp"] / 100
                if language == "da":
                    consequence = (f"Motorens bedste valg var {best['san']}. Dens bedste fortsættelse efter dit træk er "
                                   f"{reply}; trækket giver cirka {loss:.1f} bonde i vurdering sammenlignet med bedste valg."
                                   if reply else
                                   f"Motorens bedste valg var {best['san']}; dit træk giver cirka {loss:.1f} bonde i vurdering.")
                else:
                    consequence = (f"The engine's top choice was {best['san']}. Its strongest reply to your move is {reply}; "
                                   f"your move gives up about {loss:.1f} pawns of evaluation compared with that choice."
                                   if reply else
                                   f"The engine's top choice was {best['san']}; your move gives up about {loss:.1f} pawns of evaluation.")
            text = f"{label}. {consequence}"
        return {**assessment, "text": text, "fen": board.fen(), "move": move.uci(), "facts": facts,
                "played": played, "best": best, "alternatives": alternatives["candidates"],
                "resulting_observations": resulting, "consequence": consequence, "budget_ms": time_ms, "perspective": "white" if board.turn else "black",
                "takeaway": "Undersøg skakker, slag og trusler før dit næste træk." if language == "da" else "Before moving, look for checks, captures, and threats."}

    def play(self, board: chess.Board, difficulty: int = 2) -> chess.Move:
        difficulty = max(1, min(5, difficulty))
        # Deliberately imperfect move selection; levels are practice settings, not asserted Elo ratings.
        if difficulty < 5 and random.random() < {1: .55, 2: .32, 3: .15, 4: .04}[difficulty]:
            legal = list(board.legal_moves)
            return random.choice(legal)
        result = self.analyze(board, time_ms={1: 60, 2: 100, 3: 180, 4: 350, 5: 700}[difficulty], candidates=3)
        if not result["candidates"]: raise ValueError("No legal move")
        weights = [1, .6, .3] if difficulty < 4 else [1, .1, .02] if difficulty == 4 else [1, 0, 0]
        candidate = random.choices(result["candidates"], weights=weights[:len(result["candidates"])])[0]
        return chess.Move.from_uci(candidate["uci"])


engine_service = EngineService()
