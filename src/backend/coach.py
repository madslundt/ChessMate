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
        facts = best["facts"]
        piece_names = {"pawn": "bonde", "knight": "springer", "bishop": "løber", "rook": "tårn", "queen": "dronning", "king": "konge"}
        piece = piece_names.get(facts["piece"], "brik") if da else facts["piece"]
        move = chess.Move.from_uci(best["uci"])
        after = board.copy()
        after.push(move)
        attacked_major = next((square for square in after.attacks(move.to_square)
                               if after.piece_at(square) and after.color_at(square) != board.turn
                               and after.piece_type_at(square) in (chess.QUEEN, chess.ROOK)), None)
        target = chess.square_name(attacked_major) if attacked_major is not None else None
        target_piece = None
        if target:
            target_type = after.piece_type_at(attacked_major)
            target_name = chess.piece_name(target_type)
            target_piece = piece_names.get(target_name, target_name) if da else target_name

        if level == 1:
            if facts["check"]:
                text = "Start med skakker, der skaber en ekstra trussel." if da else "Start with checks that create a second threat."
            elif facts["capture"]:
                text = "Begynd med slag, og se hvad der står tilbage efter modstanderens bedste genslag." if da else "Start with captures, then see what remains after the opponent's best recapture."
            elif facts["castle"]:
                text = "Sammenlign kongens sikkerhed med dine mest presserende skakker og slag." if da else "Compare king safety with your most urgent checks and captures."
            elif facts["develops_minor"]:
                text = "Se efter en måde at forbedre en let officer og få mere kontrol over centrum." if da else "Look for a way to improve a minor piece while gaining central control."
            elif facts.get("central_control"):
                squares = ", ".join(facts["central_control"])
                text = f"Centrum er vigtigt her; se efter pres på {squares}." if da else f"The center matters here; look for ways to pressure {squares}."
            else:
                text = (f"Se først på din {piece} på {facts['from']}; den kan forbedres uden at overse modstanderens trusler." if da else
                        f"Start with your {piece} on {facts['from']}; look for an improvement that still meets the opponent's threats.")
        elif level == 2:
            if facts["check"] and target:
                text = (f"Din {piece} på {facts['from']} kan give skak og samtidig angribe modstanderens {target_piece} på {target}." if da else
                        f"Your {piece} on {facts['from']} can give check while also attacking the opponent's {target_piece} on {target}.")
            elif facts["check"]:
                text = (f"Fokuser på din {piece} på {facts['from']}; den stærkeste idé begynder med skak." if da else
                        f"Focus on your {piece} on {facts['from']}; the strongest idea starts with a check.")
            elif facts["capture"]:
                captured = piece_names.get(facts.get("captured_piece"), "brik") if da else (facts.get("captured_piece") or "piece")
                text = (f"Fokuser på din {piece} på {facts['from']}: den kan slå en {captured} på {facts['to']}. Vurdér genslaget." if da else
                        f"Focus on your {piece} on {facts['from']}: it can capture a {captured} on {facts['to']}. Check the recapture.")
            elif facts["castle"]:
                text = (f"Undersøg rokade med kongen på {facts['from']}; den bringer kongen i sikkerhed og aktiverer tårnet." if da else
                        f"Consider castling with the king on {facts['from']}; it improves king safety and activates the rook.")
            elif facts["develops_minor"]:
                text = (f"Fokuser på din {piece} på {facts['from']}; den kan udvikles til en mere aktiv plads." if da else
                        f"Focus on your {piece} on {facts['from']}; it can develop to a more active square.")
            elif facts.get("central_control"):
                squares = ", ".join(facts["central_control"])
                text = (f"Din {piece} på {facts['from']} kan øge kontrollen over {squares}." if da else
                        f"Your {piece} on {facts['from']} can increase control of {squares}.")
            else:
                text = (f"Den vigtigste brik at forbedre er din {piece} på {facts['from']}." if da else
                        f"The key piece to improve is your {piece} on {facts['from']}.")
        elif level == 3:
            text = f"{best['san']}: {move_idea(facts, language)}"
        else:
            text = f"{best['san']}: {move_idea(facts, language)}"
        side = ("Hvid" if board.turn else "Sort") if da else ("White" if board.turn else "Black")
        text = (f"{side} i trækket: " if da else f"{side} to move: ") + text
        result = {"fen": board.fen(), "level": level, "text": text, "perspective": "white" if board.turn else "black",
                  "highlight_move": best["uci"]}
        if level == 4:
            result["candidates"] = [{**c, "explanation": move_idea(c["facts"], language)} for c in candidates]
        return result


coach_service = CoachService()
