"""Bounded practice opponent, isolated from the full-strength coaching engine.

Practice levels use progressively smaller probabilities of searched inaccuracies and
mistakes. These are explicit behavior profiles, not calibrated Elo ratings.
"""
import copy
import hashlib
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence, TypeVar

import chess
import chess.engine


class OpponentUnavailable(RuntimeError):
    pass


T = TypeVar("T")


class RandomSource(Protocol):
    def choices(self, population: Sequence[T], weights: Sequence[float] | None = None,
                *, cum_weights: Sequence[float] | None = None, k: int = 1) -> list[T]: ...


@dataclass(frozen=True)
class ErrorProfile:
    pool: int
    time_ms: int
    depth: int
    # Good (<=45 CP), inaccuracy (46..120), mistake (121..300), serious error (301..700).
    bands: tuple[float, float, float, float]
    temperature: float


PROFILES = {
    1: ErrorProfile(16, 100, 6, (.10, .30, .40, .20), 90),
    2: ErrorProfile(12, 150, 8, (.32, .36, .27, .05), 60),
    3: ErrorProfile(10, 220, 10, (.64, .27, .085, .005), 35),
    4: ErrorProfile(6, 350, 12, (.94, .055, .005, 0), 15),
}


def _score(candidate: dict) -> int:
    mate = candidate.get("mate")
    return (100000 - abs(mate)) * (1 if mate > 0 else -1) if mate is not None else candidate.get("cp") or 0


def candidate_loss(best: dict, candidate: dict) -> int:
    """Policy loss: preserve mate signs without turning every missed mate into infinity."""
    best_mate, mate = best.get("mate"), candidate.get("mate")
    if best_mate is not None and best_mate > 0:
        if mate is not None and mate > 0: return 0
        if mate is None: return max(120, 400 - (candidate.get("cp") or 0))
    if mate is not None and mate <= 0:
        if best_mate is not None and best_mate <= 0:
            return max(0, (abs(best_mate) - abs(mate)) * 10)
        return 600  # A beginner can miss a deeper mating threat, but never an obvious mate-in-one escape.
    return max(0, _score(best) - _score(candidate))


def choose_candidate(candidates: list[dict], difficulty: int, rng: RandomSource) -> dict:
    """Sample a searched error band first, then plausible moves within that band."""
    if not candidates: raise ValueError("No legal opponent candidate")
    profile = PROFILES[max(1, min(4, difficulty))]
    safe = [candidate for candidate in candidates if not candidate.get("allows_mate_in_one")
            and not (candidate.get("mate") is not None and -1 <= candidate["mate"] <= 0)]
    ranked = sorted(safe or candidates, key=_score, reverse=True)
    best = ranked[0]
    bands: list[list[tuple[dict, int]]] = [[], [], [], []]
    for candidate in ranked:
        loss = candidate_loss(best, candidate)
        if loss > 700: continue  # Avoid gratuitous disasters when a searched, less damaging option exists.
        index = 0 if loss <= 45 else 1 if loss <= 120 else 2 if loss <= 300 else 3
        bands[index].append((candidate, loss))
    available = [index for index, band in enumerate(bands) if band and profile.bands[index] > 0]
    if not available: return best
    band = rng.choices(available, weights=[profile.bands[index] for index in available])[0]
    choices = bands[band]
    minimum = min(loss for _, loss in choices)
    weights = [max(.01, candidate.get("plausibility", 1)) * math.exp(-(loss - minimum) / profile.temperature)
               for candidate, loss in choices]
    return rng.choices([candidate for candidate, _ in choices], weights=weights)[0]


def allows_mate_in_one(board: chess.Board, move: chess.Move) -> bool:
    after = board.copy()
    after.push(move)
    for reply in after.legal_moves:
        if not after.gives_check(reply): continue
        continuation = after.copy()
        continuation.push(reply)
        if continuation.is_checkmate(): return True
    return False


def plausibility(board: chess.Board, move: chess.Move) -> float:
    """Small, position-aware priors; never a substitute for the searched error bands."""
    if board.fullmove_number > 10 or board.is_check() or board.is_capture(move) or board.gives_check(move): return 1
    piece = board.piece_type_at(move.from_square)
    back_rank = 0 if board.turn else 7
    if piece == chess.KING and not board.is_castling(move) and board.has_castling_rights(board.turn): return .15
    if piece == chess.QUEEN and board.fullmove_number <= 6: return .55
    if piece == chess.KNIGHT and chess.square_rank(move.to_square) == back_rank: return .35
    if piece in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) == back_rank: return 1.2
    if piece == chess.PAWN and chess.square_file(move.to_square) in (0, 7): return .7
    return 1


class OpponentService:
    def __init__(self, path: Callable[[], str | None]) -> None:
        self._path = path
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
        self._last_failure = -math.inf

    def _get_engine(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            path = self._path()
            if not path or time.monotonic() - self._last_failure < 3:
                raise OpponentUnavailable("Stockfish is unavailable for the practice opponent")
            try:
                self._engine = chess.engine.SimpleEngine.popen_uci(path, timeout=8)
                options = {"Threads": 1, "Hash": 16, "Skill Level": 20, "UCI_LimitStrength": False}
                self._engine.configure({key: value for key, value in options.items() if key in self._engine.options})
            except (OSError, chess.engine.EngineError, TimeoutError) as exc:
                if self._engine: self._engine.close()
                self._engine = None
                self._last_failure = time.monotonic()
                raise OpponentUnavailable("The practice opponent could not start") from exc
        return self._engine

    @staticmethod
    def _search(engine: chess.engine.SimpleEngine, board: chess.Board, profile: ErrorProfile,
                root_moves: list[chess.Move] | None = None) -> list[dict]:
        infos = engine.analyse(board, chess.engine.Limit(time=profile.time_ms / 1000, depth=profile.depth),
            multipv=min(profile.pool, len(root_moves) if root_moves else board.legal_moves.count()),
            root_moves=root_moves, game=object())  # New UCI game: no stronger earlier search warms a weaker profile.
        result = []
        for info in infos:
            pv = info.get("pv", [])
            if not pv or pv[0] not in board.legal_moves: continue
            score = info["score"].pov(board.turn)
            move = pv[0]
            result.append({"uci": move.uci(), "cp": score.score(), "mate": score.mate(), "depth": info.get("depth", 0),
                "pv_uci": [value.uci() for value in pv[:3]], "allows_mate_in_one": allows_mate_in_one(board, move),
                "plausibility": plausibility(board, move)})
        return result

    def candidates(self, board: chess.Board, difficulty: int) -> list[dict]:
        if not board.is_valid(): raise ValueError("Invalid chess position")
        if board.is_game_over(claim_draw=True): raise ValueError("No legal move: the game has ended")
        profile = PROFILES[max(1, min(4, difficulty))]
        key = hashlib.sha256(repr((board.fen(), [move.uci() for move in board.move_stack], profile)).encode()).hexdigest()
        if not self._lock.acquire(timeout=2): raise OpponentUnavailable("The practice opponent is busy; retry shortly")
        try:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < 300:
                self._cache.move_to_end(key)
                return copy.deepcopy(cached[1])
            engine = self._get_engine()
            try:
                result = self._search(engine, board, profile)
                if result and all(candidate["allows_mate_in_one"] for candidate in result):
                    # A limited search can omit the only defense. Inspect legal alternatives,
                    # then search the defenses rather than falling back to random legal moves.
                    defenses = [move for move in board.legal_moves if not allows_mate_in_one(board, move)]
                    if defenses: result = self._search(engine, board, profile, root_moves=defenses)
            except (chess.engine.EngineError, TimeoutError, OSError) as exc:
                engine.close()
                self._engine = None
                self._last_failure = time.monotonic()
                raise OpponentUnavailable("Practice opponent analysis failed; retry shortly") from exc
            if not result: raise OpponentUnavailable("The practice opponent returned no legal candidate")
            self._cache[key] = (time.monotonic(), copy.deepcopy(result))
            while len(self._cache) > 128: self._cache.popitem(last=False)
            return result
        finally:
            self._lock.release()

    def choose(self, board: chess.Board, difficulty: int, rng: RandomSource) -> chess.Move:
        if not board.is_valid(): raise ValueError("Invalid chess position")
        if board.is_game_over(claim_draw=True): raise ValueError("No legal move: the game has ended")
        legal = list(board.legal_moves)
        if len(legal) == 1: return legal[0]
        candidate = choose_candidate(self.candidates(board, difficulty), difficulty, rng)
        return chess.Move.from_uci(candidate["uci"])

    def close(self) -> None:
        with self._lock:
            if self._engine:
                try: self._engine.quit()
                except (chess.engine.EngineError, TimeoutError): self._engine.close()
                self._engine = None
            self._cache.clear()
