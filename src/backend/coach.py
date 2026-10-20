"""Evidence-only coaching. The model chooses verified statements, never invents moves."""
import asyncio
import json
import ssl
import threading
from typing import Literal

import chess
import httpx
from pydantic import BaseModel, ConfigDict, Field

from .chess_tools import move_facts, move_idea, observations, parse_move
from .coach_facts import PIECES_DA, build_statements, learner_color, fallback_keys, reveal_requested, show_line, visible_candidates
from .config import settings, llm_tls_context
from .engine import EngineUnavailable, engine_service
from .llm_settings import Connection


class ModelUnavailable(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def model_failure_reason(error: Exception) -> str:
    if isinstance(error, ModelUnavailable): return error.reason
    if isinstance(error, (httpx.TimeoutException, asyncio.TimeoutError)): return "timeout"
    if isinstance(error, httpx.HTTPStatusError):
        return "authentication" if error.response.status_code in (401, 403) else "server_error"
    if isinstance(error, httpx.ConnectError):
        cause, seen = error, set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, ssl.SSLCertVerificationError): return "tls_certificate"
            cause = cause.__cause__ or cause.__context__
        return "connection"
    if isinstance(error, httpx.HTTPError): return "connection"
    return "invalid_response"


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_ids: list[str] = Field(default_factory=list, max_length=5)
    candidate_uci: str | None = None
    pv_uci: list[str] = Field(default_factory=list, max_length=10)
    tone: Literal["explain", "question"] = "explain"
    response: str = Field(default="", max_length=3000)


class CoachService:
    def __init__(self):
        self._slots = threading.BoundedSemaphore(2)

    def context(self, board: chess.Board, preferences: dict, question: str, history: list[dict],
                game_context: dict | None = None, analysis: dict | None = None) -> dict:
        if analysis is None:
            try: analysis = engine_service.analyze(board, time_ms=preferences.get("analysis_time_ms", 250))
            except EngineUnavailable: analysis = {"fen": board.fen(), "candidates": [], "source": "unavailable", "observations": observations(board)}
        if analysis["fen"] != board.fen(): raise ValueError("Analysis position does not match coach position")
        # User-specified legal candidate moves can be evaluated, with exact position provenance.
        requested = []
        for token in question.split():
            token = token.strip(".,!?;:()[]\"\'")
            try:
                move = parse_move(board, token)
                if move.uci() not in requested: requested.append(move.uci())
            except ValueError: continue
        if board.turn == learner_color(board, {"game": game_context or {}}) and any(word in question.lower() for word in ("castle", "rokad")):
            requested.extend(m.uci() for m in board.legal_moves if board.is_castling(m) and m.uci() not in requested)
        candidate_evidence = []
        for value in requested[:2]:
            try:
                evidence = engine_service.analyze(board, time_ms=150, candidates=1, root_moves=[chess.Move.from_uci(value)])
                candidate_evidence.extend(evidence["candidates"])
            except EngineUnavailable: break
        unavailable_piece_choices = []
        if not requested and any(term in question.lower() for term in ("better than", "rather than", "compare", "bedre end", "sammenlign")):
            for piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.PAWN, chess.KING):
                name = chess.piece_name(piece_type)
                if name not in question.lower() and PIECES_DA[name] not in question.lower(): continue
                choices = [m for m in board.legal_moves if board.piece_type_at(m.from_square) == piece_type]
                if not choices:
                    unavailable_piece_choices.append(name)
                    continue
                try:
                    evidence = engine_service.analyze(board, time_ms=150, candidates=1, root_moves=choices)
                    candidate_evidence.extend(evidence["candidates"])
                except EngineUnavailable: break
                if len(candidate_evidence) >= 2: break
        return {"fen": board.fen(), "learner_color": "white" if learner_color(board, {"game": game_context or {}}) else "black", "side_to_move": "white" if board.turn else "black",
                "legal_moves": [{"uci": m.uci(), "san": board.san(m)} for m in board.legal_moves],
                "move_history": [m.uci() for m in board.move_stack[-16:]], "analysis": analysis,
                "requested_candidates": candidate_evidence, "unavailable_piece_choices": unavailable_piece_choices, "phase": analysis.get("observations", {}).get("phase"),
                "skill_level": preferences.get("complexity", "beginner"), "preferences": preferences,
                "game": game_context or {}, "history": history[-8:], "question": question}

    def statements(self, board: chess.Board, context: dict, language: str, reveal: bool) -> dict[str, str]:
        return build_statements(board, context, language, reveal)

    @staticmethod
    def validate_selection(selection: Selection, statements: dict, board: chess.Board, context: dict, reveal: bool) -> None:
        if any(key not in statements for key in selection.fact_ids): raise ValueError("Unsupported coaching statement")
        if not selection.response.strip() and not selection.fact_ids: raise ValueError("Empty coaching response")
        candidates = visible_candidates(context, reveal)
        if reveal and not candidates and not context.get("question"):
            candidates = context["analysis"].get("candidates", [])
        allowed = {c["uci"] for c in candidates}
        if selection.candidate_uci:
            if not reveal or selection.candidate_uci not in allowed: raise ValueError("Unverified candidate")
            parse_move(board, selection.candidate_uci)
        if selection.pv_uci:
            if not reveal or not show_line(context): raise ValueError("Spoilers disabled")
            if not any(c.get("pv_uci", [])[:len(selection.pv_uci)] == selection.pv_uci for c in candidates):
                raise ValueError("Variation is not part of verified evidence")
            variation = board.copy()
            for value in selection.pv_uci: variation.push(parse_move(variation, value))

    async def _model_selection(self, context: dict, statements: dict, llm: Connection | None = None) -> Selection:
        llm = llm or Connection(settings.llm_base_url, settings.llm_model, settings.llm_api_key)
        if not llm.base_url or not llm.model: raise ModelUnavailable("not_configured")
        acquired = await asyncio.to_thread(self._slots.acquire, True, 2)
        if not acquired: raise ModelUnavailable("busy")
        try:
            instruction = (
                "You are a patient chess teacher. All chess facts are supplied by a verified engine and legal board tools. "
                "Answer the user's actual question directly in natural language in the response field. Do not repeat a generic "
                "hint when it does not answer the question. For ordinary non-chess questions, answer normally. For chess claims, "
                "use only the verified statement catalog: do not invent position facts, evaluations, moves, or variations. "
                "If a chess question cannot be answered from the catalog, say what information is missing. "
                "Select the supporting fact_ids when applicable; these are checked against the catalog. Only reference candidate "
                "moves and PVs supplied in the verified context. General principles are suggestions, and geometric attacks do not "
                "prove a profitable capture. Return ONLY JSON with response, fact_ids, candidate_uci, pv_uci, tone, for example "
                '{"response":"The answer is 4.","fact_ids":[],"candidate_uci":null,"pv_uci":[],"tone":"explain"}. '
                "Use question tone for Socratic coaching."
            )
            payload = {"model": llm.model, "messages": [{"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps({"verified_context": context, "statement_catalog": statements})}],
                "temperature": settings.llm_temperature, "max_tokens": settings.llm_max_tokens, "stream": True}
            if settings.llm_reasoning_effort:
                payload["reasoning_effort"] = settings.llm_reasoning_effort
            url = llm.base_url
            if not url.endswith("/v1"): url += "/v1"
            headers = {"Authorization": f"Bearer {llm.api_key}"} if llm.api_key else {}
            chunks, size = [], 0
            async with httpx.AsyncClient(timeout=settings.llm_timeout,
                                         verify=llm_tls_context() if llm.verify_tls else False) as client:
                async with client.stream("POST", url + "/chat/completions", json=payload, headers=headers) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"): continue
                        data = line[5:].strip()
                        if data == "[DONE]": break
                        item = json.loads(data)
                        choices = item.get("choices", [])
                        fragment = choices[0].get("delta", {}).get("content", "") if choices else ""
                        if fragment:
                            size += len(fragment)
                            if size > 12000: raise ValueError("Model response too large")
                            chunks.append(fragment)
            raw = "".join(chunks).strip()
            if raw.startswith("```json") and raw.endswith("```"): raw = raw[7:-3].strip()
            return Selection.model_validate_json(raw)
        finally:
            self._slots.release()

    async def respond(self, board: chess.Board, context: dict, language: str, llm: Connection | None = None) -> tuple[str, str, str | None]:
        preferences = context["preferences"]
        reveal = reveal_requested(context) or not preferences.get("hide_best_moves", True)
        statements = self.statements(board, context, language, reveal)
        keys = fallback_keys(context, statements, reveal)
        source = "deterministic"
        fallback_reason = None
        try:
            # Total deadline also bounds servers that send tiny deltas indefinitely.
            request = self._model_selection(context, statements, llm) if llm is not None else self._model_selection(context, statements)
            selection = await asyncio.wait_for(request, timeout=settings.llm_timeout + 2)
            self.validate_selection(selection, statements, board, context, reveal)
            if selection.response.strip():
                max_words = preferences.get("max_explanation_length", 120)
                text = " ".join(selection.response.split()[:max_words])
                return text, "local_llm_verified", None
            keys = list(dict.fromkeys(selection.fact_ids))
            if "review" in statements:
                keys = list(dict.fromkeys([key for key in ("review", "previous_assessment") if key in statements] + keys))
            source = "local_llm_verified"
        except (RuntimeError, ValueError, httpx.HTTPError, asyncio.TimeoutError, KeyError, TypeError) as error:
            fallback_reason = model_failure_reason(error)
        max_words = preferences.get("max_explanation_length", 120)
        selected, count = [], 0
        for key in keys:
            sentence = statements[key]
            if selected and count + len(sentence.split()) > max_words: break
            selected.append(sentence)
            count += len(sentence.split())
        return " ".join(selected), source, fallback_reason

    def hint(self, board: chess.Board, level: int, language: str = "en", time_ms: int = 250, depth: int | None = None, candidates: int = 3) -> dict:
        analysis = engine_service.analyze(board, candidates=candidates, time_ms=time_ms, depth=depth)
        da = language == "da"
        candidates = analysis["candidates"]
        if not candidates:
            return {"fen": board.fen(), "level": level, "text": "Stillingen er afsluttet." if da else "This position has ended.", "candidates": []}
        best = candidates[0]
        if level == 1:
            phase = analysis["observations"]["phase"]
            text = ({"opening": "Overvej udvikling, centrum og kongens sikkerhed.", "middlegame": "Undersøg skakker, slag og trusler for begge sider.",
                     "endgame": "Overvej kongens aktivitet og bøndernes muligheder."}[phase] if da else
                    {"opening": "Think about development, the center, and king safety.", "middlegame": "Look for checks, captures, and threats for both sides.",
                     "endgame": "Consider king activity and pawn promotion opportunities."}[phase])
        elif level == 2:
            if best["facts"]["check"]: text = "Undersøg de mulige skakker." if da else "Examine the available checks."
            elif best["facts"]["capture"]: text = "Undersøg de lovlige slag og svarene." if da else "Look closely at the legal captures and their possible replies."
            else: text = "Sammenlign brikkernes aktivitet efter hvert kandidat-træk." if da else "Compare how each candidate changes your pieces' activity."
        elif level == 3:
            piece = best["facts"]["piece"]
            names = {"pawn": "bonde", "knight": "springer", "bishop": "løber", "rook": "tårn", "queen": "dronning", "king": "konge"}
            text = f"Undersøg lovlige træk med en {names[piece]}." if da else f"Look for a useful move with a {piece}."
        else: text = f"{best['san']}: {move_idea(best['facts'], language)}"
        side = ("Hvid" if board.turn else "Sort") if da else ("White" if board.turn else "Black")
        text = (f"{side} i trækket: " if da else f"{side} to move: ") + text
        result = {"fen": board.fen(), "level": level, "text": text, "perspective": "white" if board.turn else "black"}
        if level == 4:
            result["candidates"] = [{**c, "explanation": move_idea(c["facts"], language)} for c in candidates]
        return result


coach_service = CoachService()
