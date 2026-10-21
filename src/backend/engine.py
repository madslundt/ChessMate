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

from .chess_tools import move_facts, move_idea, move_insights, observations
from .config import settings
from .coaching_strategy import candidate_strategy, strategic_facts, strategic_insights
from .opponent import OpponentService, OpponentUnavailable


class EngineUnavailable(RuntimeError):
    pass


class AnalysisCancelled(RuntimeError):
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
    elif pm is not None and pm <= 0 and not (bm is not None and bm <= 0):
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


def _material_loss_reason(board: chess.Board, variation: dict, language: str) -> str:
    """Explain material lost in the legal played line, without calling it forced."""
    loss = -variation["material_change"]
    if loss <= 0 or variation["terminal"]:
        return ""
    replay = board.copy()
    victims = []
    for value in variation["moves"]:
        move = chess.Move.from_uci(value)
        if replay.turn != board.turn and replay.is_capture(move):
            square = move.to_square + (-8 if replay.turn else 8) if replay.is_en_passant(move) else move.to_square
            victims.append((replay.piece_type_at(square), chess.square_name(square)))
        replay.push(move)
    detail = ""
    if victims:
        piece, square = max(victims, key=lambda item: {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}[item[0]])
        name = chess.piece_name(piece)
        if language == "da":
            name = {"pawn": "bonde", "knight": "springer", "bishop": "løber", "rook": "tårn", "queen": "dronning"}[name]
            detail = f"I motorvarianten efter dit træk slår modstanderen din {name} på {square}. "
        else:
            detail = f"In the engine continuation after your move, the opponent captures your {name} on {square}. "
    return detail + (f"Ved slutningen af denne variant har din side et nettotab af materiale svarende til {loss} {'bonde' if loss == 1 else 'bønder'}. Andre svar kan ændre resultatet." if language == "da" else
                     f"By the end of this continuation, your side has a net loss of material worth {loss} {'pawn' if loss == 1 else 'pawns'}. Other replies may change the result.")


class EngineService:
    def __init__(self, deep_worker: bool = False):
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._last_failure = 0.0
        self._deep_service: EngineService | None = None
        self._deep_worker = deep_worker
        self._opponent = OpponentService(lambda: self.path())

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
        self._opponent.close()
        if self._deep_service:
            self._deep_service.close()
        with self._lock:
            if self._engine:
                try: self._engine.quit()
                except (chess.engine.EngineError, TimeoutError): self._engine.close()
                self._engine = None

    def analyze(self, board: chess.Board, time_ms: int = 250, depth: int | None = None,
                candidates: int = 3, root_moves: list[chess.Move] | None = None, mode: str = "quick",
                cancel_event: threading.Event | None = None) -> dict:
        if cancel_event and cancel_event.is_set(): raise AnalysisCancelled("Analysis cancelled")
        if mode not in ("quick", "deep"): raise ValueError("Unknown analysis mode")
        # A separate bounded engine keeps an explicit long search off the gameplay worker.
        if mode == "deep":
            with self._lock:
                if self._deep_service is None: self._deep_service = EngineService(deep_worker=True)
            kwargs = {"cancel_event": cancel_event} if cancel_event is not None else {}
            result = self._deep_service.analyze(board, time_ms=max(5000, min(20000, time_ms)), depth=depth,
                candidates=candidates, root_moves=root_moves, **kwargs)
            result["mode"] = "deep"
            return result
        if not board.is_valid(): raise ValueError("Invalid chess position")
        if root_moves and any(move not in board.legal_moves for move in root_moves):
            raise ValueError("Illegal root move")
        time_ms = max(50, min(20000 if self._deep_worker else 3000, time_ms))
        candidates = max(1, min(3, candidates))
        depth = max(1, min(24, depth)) if depth else None
        key = hashlib.sha256(repr((board.fen(), [m.uci() for m in board.move_stack], time_ms, depth,
                                    candidates, [m.uci() for m in root_moves] if root_moves else None)).encode()).hexdigest()
        result = {"fen": board.fen(), "perspective": "white" if board.turn else "black",
                  "candidates": [], "observations": observations(board), "source": "stockfish",
                  "mode": mode, "budget_ms": time_ms, "confidence": "search_estimate"}
        result["strategic_facts"] = strategic_facts(board)
        result["strategic_insights"] = strategic_insights(board, board.turn)
        if board.is_game_over(claim_draw=True):
            result["terminal"] = board.outcome(claim_draw=True).termination.name.lower()
            return result
        # A finite queue avoids unlimited worker backlog when many requests arrive.
        if not self._lock.acquire(timeout=2): raise EngineUnavailable("Engine is busy; retry shortly")
        try:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < 600:
                self._cache.move_to_end(key)
                return copy.deepcopy(cached[1])
            engine = self._get_engine()
            try:
                budget = chess.engine.Limit(time=time_ms / 1000, depth=depth)
                multipv = min(candidates, len(root_moves) if root_moves else board.legal_moves.count())
                if cancel_event is None:
                    infos = engine.analyse(board, budget, multipv=multipv, root_moves=root_moves)
                else:
                    finished = threading.Event()
                    with engine.analysis(board, budget, multipv=multipv, root_moves=root_moves) as search:
                        def watch_cancel():
                            while not finished.wait(.04):
                                if cancel_event.is_set():
                                    search.stop()
                                    return
                        watcher = threading.Thread(target=watch_cancel, daemon=True)
                        watcher.start()
                        try:
                            search.wait()
                            infos = search.multipv
                        finally:
                            finished.set()
                            watcher.join(timeout=.2)
                    if cancel_event.is_set(): raise AnalysisCancelled("Analysis cancelled")
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
                    candidate["insights"], candidate["variations"] = move_insights(board, candidate)
                    candidate["strategy"] = candidate_strategy(board, candidate)
                    candidate["insights"].extend(candidate["strategy"]["effects"])
            result["analysis_key"] = key
            self._cache[key] = (time.monotonic(), copy.deepcopy(result))
            while len(self._cache) > 256: self._cache.popitem(last=False)
            return result
        finally:
            self._lock.release()

    def grade(self, board: chess.Board, move: chess.Move, time_ms: int = 250, language: str = "en", complexity: str = "beginner",
              mode: str = "quick", cancel_event: threading.Event | None = None) -> dict:
        # Both searches begin at the identical root, share a time/depth budget, and use root POV.
        # One full root search followed by a constrained root search avoids opponent-POV mistakes.
        options = {"mode": mode, "cancel_event": cancel_event} if mode != "quick" or cancel_event is not None else {}
        alternatives = self.analyze(board, time_ms=time_ms, candidates=3, **options)
        if not alternatives["candidates"]: raise ValueError("Game already over")
        played = self.analyze(board, time_ms=time_ms, candidates=1, root_moves=[move], **options)["candidates"][0]
        best = alternatives["candidates"][0]
        effective_depth = min(best["depth"], played["depth"])
        assessment = classify_move(best, played, board.legal_moves.count() == 1, effective_depth)
        initial = assessment["classification"]
        rechecked = False
        # Serious feedback must survive a second, larger search of BOTH alternatives at the same root.
        if mode == "quick" and board.legal_moves.count() > 1 and (initial in ("Mistake", "Blunder") or score_number(played) > score_number(best) + 35):
            rechecked = True
            budget = min(3000, max(600, time_ms * 2))
            alternatives = self.analyze(board, time_ms=budget, candidates=3, **options)
            played = self.analyze(board, time_ms=budget, candidates=1, root_moves=[move], **options)["candidates"][0]
            best = alternatives["candidates"][0]
            effective_depth = min(best["depth"], played["depth"])
            assessment = classify_move(best, played, False, effective_depth)
            if (initial in ("Mistake", "Blunder") and assessment["classification"] not in ("Mistake", "Blunder") or
                    score_number(played) > score_number(best) + 35):
                assessment.update(classification="Uncertain", confidence="unstable_search")
            else:
                assessment["confidence"] = "rechecked_estimate"
        # Independent short searches are noisy. A large disagreement on an identical move is never a blunder.
        if best["uci"] == move.uci() and effective_depth >= 8:
            assessment.update(classification="Best", loss_cp=0, win_chance_loss=0)
        if mode == "deep" and effective_depth >= 8:
            rechecked = True
            if score_number(played) > score_number(best) + 35:
                assessment.update(classification="Uncertain", confidence="unstable_search")
            else:
                assessment["confidence"] = "rechecked_estimate"
        facts = move_facts(board, move)
        labels = {"Best": "Bedste træk", "Excellent": "Fremragende", "Good": "Godt træk", "Inaccuracy": "Unøjagtighed",
                  "Mistake": "Fejl", "Blunder": "Alvorlig fejl", "Forced": "Tvunget træk", "Uncertain": "Usikker vurdering"}
        label = labels.get(assessment["classification"]) if language == "da" else assessment["classification"]
        text = f"{label}. {move_idea(facts, language)}"
        if assessment["classification"] in ("Best", "Excellent", "Good") and facts["capture"] and not facts.get("checkmate"):
            captured_piece = facts.get("captured_piece") or "pawn"
            if language == "da":
                captured_piece = {"pawn": "bonde", "knight": "springer", "bishop": "løber", "rook": "tårn", "queen": "dronning"}.get(captured_piece, "brik")
            difference = assessment["loss_cp"] / 100
            if language == "da":
                if facts.get("legal_reply_captures"):
                    explanation = (f"Du slår en {captured_piece}; {facts['legal_reply_captures'][0]} er et lovligt genslag. "
                                   f"Søgningen vurderer trækket {difference:.1f} bonde under sit bedste valg; undersøg dens variant.")
                else:
                    explanation = (f"Du slår en {captured_piece}, som ikke straks kan slås tilbage på {facts['to']}; "
                                   f"undersøg andre trusler, før du regner materialet som vundet. Søgningen ligger {difference:.1f} bonde fra sit bedste valg.")
            elif facts.get("legal_reply_captures"):
                explanation = (f"You take a {captured_piece}; {facts['legal_reply_captures'][0]} is a legal recapture. "
                               f"The search rates your move {difference:.1f} pawns below its top choice; examine its continuation.")
            else:
                explanation = (f"You take a {captured_piece} with no immediate legal recapture on {facts['to']}, "
                               f"but other threats still need checking. The move stays {difference:.1f} pawns from the engine's top choice.")
            text = f"{label}. {explanation}"
        after = board.copy()
        after.push(move)
        resulting = observations(after)
        exposed = facts.get("newly_exposed_own", [])
        insights, variations = move_insights(board, played, language)
        strategy = candidate_strategy(board, played, language, complexity)
        material_reason = _material_loss_reason(board, variations[0], language) if variations else ""
        consequence = ""
        reply_san, reply_mates = None, False
        if len(played.get("pv_uci", [])) > 1:
            reply_move = chess.Move.from_uci(played["pv_uci"][1])
            if reply_move in after.legal_moves:
                reply_san = after.san(reply_move)
                reply_board = after.copy()
                reply_board.push(reply_move)
                reply_mates = reply_board.is_checkmate()
        if assessment["classification"] in ("Mistake", "Blunder", "Inaccuracy"):
            if facts.get("stalemate"):
                consequence = ("Trækket giver pat: modstanderen står ikke i skak og har ingen lovlige træk. Partiet er remis." if language == "da" else
                    "This move causes stalemate: the opponent is not in check and has no legal moves. The game is drawn.")
            elif after.is_insufficient_material():
                consequence = ("Trækket efterlader utilstrækkeligt materiale til skakmat. Partiet er remis." if language == "da" else
                    "This move leaves insufficient mating material. The game is drawn.")
            elif played.get("mate") is not None and played["mate"] <= 0:
                if reply_mates:
                    king = chess.square_name(after.king(board.turn))
                    consequence = (f"Modstanderen har det lovlige matsvar {reply_san}. Din konge på {king} står i skak, og intet lovligt svar ophæver skakken." if language == "da" else
                        f"The opponent has a legal checkmating reply: {reply_san}. Your king on {king} is in check, and no legal response resolves it.")
                else:
                    consequence = ("Motoren finder en tvungen mat mod dig." if language == "da" else
                                   "The engine finds a forced mate against you.")
                    if reply_san:
                        consequence += (f" I motorvarianten svarer modstanderen med {reply_san}." if language == "da" else
                                        f" In the engine continuation, the opponent replies {reply_san}.")
            elif material_reason:
                consequence = material_reason
            elif exposed:
                squares = ", ".join(p["square"] for p in exposed[:2])
                removed = [p["square"] for p in facts.get("removed_geometric_support", []) if p["square"] in squares.split(", ")]
                if removed:
                    consequence = (f"Ved at flytte fra {facts['from']} fjerner brikken sin geometriske støtte til {', '.join(removed)}. Brikken er nu angrebet og geometrisk udækket; undersøg de lovlige slag." if language == "da" else
                        f"Moving from {facts['from']} removes the piece's geometric support of {', '.join(removed)}. That piece is now attacked and geometrically undefended; check the legal captures.")
                else:
                    consequence = (f"Trækket efterlader dine brikker på {squares} angrebet og geometrisk udækkede; denne kombination var ikke til stede før trækket. Undersøg de lovlige slag." if language == "da" else
                        f"This move leaves your pieces on {squares} attacked and geometrically undefended; that combination was absent before the move. Check the legal captures.")
            elif facts.get("legal_reply_captures"):
                consequence = (f"Modstanderen kan lovligt slå din brik på {facts['to']}. Undersøg hele byttefølgen." if language == "da" else
                               f"The opponent has a legal capture of the moved piece on {facts['to']}. Examine the full exchange.")
                consequence += (" Slaget alene beviser ikke, at du taber materiale eller forklarer hele vurderingen." if language == "da" else
                                " That capture alone does not prove a material loss or explain the full assessment.")
            else:
                consequence = ("Søgningen vurderer stillingen efter dit træk som svagere, men en konkret taktisk eller positionel årsag er ikke verificeret." if language == "da" else
                               "The search evaluates the position after your move as weaker, but a concrete tactical or positional reason has not been verified.")
                if reply_san:
                    consequence += (f" I motorvarianten svarer modstanderen med {reply_san}." if language == "da" else
                                    f" In the engine continuation, the opponent replies {reply_san}.")
            text = f"{label}. {consequence}"
        insights.extend(strategy["effects"])
        if strategy["effects"] and assessment["classification"] in ("Best", "Excellent", "Good") and not facts["capture"] and not facts["check"]:
            text = f"{label}. {move_idea(facts, language)} {strategy['plan']}"
        alternative_lines = []
        for candidate in alternatives["candidates"]:
            if candidate["uci"] != move.uci():
                _, lines = move_insights(board, candidate, language)
                alternative_lines.extend(lines)
        return {**assessment, "text": text, "fen": board.fen(), "move": move.uci(), "facts": facts,
                "insights": insights, "variations": variations, "alternative_variations": alternative_lines,
                "strategy": strategy, "complexity": complexity,
                "analysis_mode": mode,
                "rechecked": rechecked, "search_depth": effective_depth,
                "played": played, "best": best, "alternatives": alternatives["candidates"],
                "resulting_observations": resulting, "consequence": consequence, "budget_ms": time_ms, "perspective": "white" if board.turn else "black",
                "takeaway": "Undersøg skakker, slag og trusler før dit næste træk." if language == "da" else "Before moving, look for checks, captures, and threats."}

    def play(self, board: chess.Board, difficulty: int = 2) -> chess.Move:
        difficulty = max(1, min(5, difficulty))
        if difficulty < 5:
            try: return self._opponent.choose(board, difficulty, random)
            except OpponentUnavailable as exc: raise EngineUnavailable(str(exc)) from exc
        # The strongest setting preserves full-strength analysis; coaching preferences never set opponent strength.
        result = self.analyze(board, time_ms=700, candidates=3)
        if not result["candidates"]: raise ValueError("No legal move")
        return chess.Move.from_uci(result["candidates"][0]["uci"])


engine_service = EngineService()
