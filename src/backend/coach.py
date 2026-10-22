"""Evidence-only coaching. The model chooses verified statements, never invents moves."""
import asyncio
import json
import ssl
import threading
from typing import Literal

import chess
import httpx
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .chess_tools import move_facts, move_idea, move_insights, observations, parse_move, resolve_move_references
from .coach_facts import PIECES_DA, build_statements, learner_color, fallback_keys, reveal_requested, show_line, visible_candidates
from .config import settings, llm_tls_context
from .engine import EngineUnavailable, engine_service, score_number
from .llm_settings import Connection
from .coaching_strategy import strategic_insights, candidate_strategy
from .coaching_language import verified_paraphrase
from .coaching_choices import choice_moves, choice_recommendation, piece_choice_request, piece_choice_statements
from .coaching_conversation import resolve_question


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


class ExplanationSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_id: str
    framing: Literal["plain", "notice", "consider", "test", "connect", "reflect"] = "plain"
    paraphrase: str | None = Field(default=None, max_length=1800, validation_alias=AliasChoices("paraphrase", "text"))


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_ids: list[str] = Field(default_factory=list, max_length=5)
    candidate_uci: str | None = None
    pv_uci: list[str] = Field(default_factory=list, max_length=10)
    tone: Literal["explain", "question"] = "explain"
    response: str = Field(default="", max_length=3000)
    segments: list[ExplanationSegment] = Field(default_factory=list, max_length=8)


def grounded_response(selection: Selection, statements: dict, language: str) -> str:
    """Render evidence references, rejecting ANY factual prose outside verified spans.

    The model controls relevance, order, framing, and composition of dynamic board/engine
    insights. A fact id alongside unchecked prose is never treated as verification.
    Legacy prose is accepted only when it exactly reproduces its cited evidence.
    """
    if selection.segments:
        rendered = []
        for segment in selection.segments:
            if segment.fact_id not in statements: raise ValueError("Unsupported explanation evidence")
            prefix = {"plain": "", "notice": "Bemærk: " if language == "da" else "Notice: ",
                      "consider": "Overvej: " if language == "da" else "Consider: ",
                      "test": "For at teste idéen: " if language == "da" else "To test the idea: ",
                      "connect": "Dernæst: " if language == "da" else "Next, ",
                      "reflect": "Til din overvejelse: " if language == "da" else "For reflection: "}[segment.framing]
            sentence = verified_paraphrase(segment.paraphrase, statements[segment.fact_id]) if segment.paraphrase else statements[segment.fact_id]
            rendered.append(prefix + sentence)
        if selection.response.strip(): raise ValueError("Cannot mix grounded segments and unchecked prose")
        return " ".join(rendered)
    if selection.response.strip():
        cited = " ".join(statements[key] for key in selection.fact_ids)
        if " ".join(selection.response.split()) != " ".join(cited.split()):
            raise ValueError("Unverified explanation prose")
        return cited
    return ""


class CoachService:
    def __init__(self):
        self._slots = threading.BoundedSemaphore(2)

    def context(self, board: chess.Board, preferences: dict, question: str, history: list[dict],
                game_context: dict | None = None, analysis: dict | None = None, topic: dict | None = None) -> dict:
        history = [message for message in history if message.get("fen") in (None, board.fen())]
        user_question = question
        question, follow_up, anchor = resolve_question(question, history, topic, board.fen())
        if analysis is None:
            try: analysis = engine_service.analyze(board, time_ms=preferences.get("analysis_time_ms", 250))
            except EngineUnavailable: analysis = {"fen": board.fen(), "candidates": [], "source": "unavailable", "observations": observations(board)}
        if analysis["fen"] != board.fen(): raise ValueError("Analysis position does not match coach position")
        # User-specified legal candidate moves can be evaluated, with exact position provenance.
        resolved = resolve_move_references(board, question)
        requested = resolved["moves"]
        if not anchor and board.turn == learner_color(board, {"game": game_context or {}}) and any(word in question.lower() for word in ("castle", "rokad")):
            requested.extend(m.uci() for m in board.legal_moves if board.is_castling(m) and m.uci() not in requested)
        candidate_evidence = []
        for value in ([] if anchor else requested[:2]):
            try:
                evidence = engine_service.analyze(board, time_ms=150, candidates=1, root_moves=[chess.Move.from_uci(value)])
                candidate_evidence.extend(evidence["candidates"])
            except EngineUnavailable: break
        unavailable_piece_choices = []
        piece_choice = piece_choice_request(question) if not requested else None
        if piece_choice and not anchor and board.turn == learner_color(board, {"game": game_context or {}}):
            piece_choice["analyzed"] = True
            for piece_type in piece_choice["pieces"]:
                name = chess.piece_name(piece_type)
                choices = choice_moves(board, piece_type, piece_choice["development"])
                if not choices:
                    unavailable_piece_choices.append(name)
                    continue
                try:
                    evidence = engine_service.analyze(board, time_ms=150, candidates=1, root_moves=choices)
                    candidate_evidence.extend(evidence["candidates"])
                    if not evidence["candidates"]: piece_choice["analyzed"] = False
                except EngineUnavailable:
                    piece_choice["analyzed"] = False
            candidate_evidence.sort(key=score_number, reverse=True)
        topic_focus = None
        if anchor:
            # Only server-persisted evidence for this exact board can pin a prior
            # recommendation. Recheck legality before rendering any saved move.
            for candidate in anchor.get("requested_candidates", []): parse_move(board, candidate["uci"])
            if anchor.get("focus_candidate"): parse_move(board, anchor["focus_candidate"]["uci"])
            candidate_evidence = anchor.get("requested_candidates", [])
            piece_choice = anchor.get("piece_choice")
            unavailable_piece_choices = anchor.get("unavailable_piece_choices", [])
            topic_focus = anchor.get("focus_candidate")
        return {"fen": board.fen(), "learner_color": "white" if learner_color(board, {"game": game_context or {}}) else "black", "side_to_move": "white" if board.turn else "black",
                "legal_moves": [{"uci": m.uci(), "san": board.san(m)} for m in board.legal_moves],
                "move_history": [m.uci() for m in board.move_stack[-16:]], "analysis": analysis,
                "requested_candidates": candidate_evidence, "ambiguous_moves": resolved["ambiguous"],
                "unavailable_piece_choices": unavailable_piece_choices, "piece_choice": piece_choice, "phase": analysis.get("observations", {}).get("phase"),
                "skill_level": preferences.get("complexity", "beginner"), "preferences": preferences,
                "game": game_context or {}, "history": history[-8:], "question": question,
                "user_question": user_question, "follow_up": follow_up, "topic_focus": topic_focus,
                "missing_topic": bool(follow_up and question == user_question and not anchor)}

    def statements(self, board: chess.Board, context: dict, language: str, reveal: bool) -> dict[str, str]:
        statements = build_statements(board, context, language, reveal)
        state = context.get("coaching_state", {})
        if state.get("acknowledgement"): statements["discovery_acknowledgement"] = state["acknowledgement"]
        if state.get("mode") == "guided" and not context.get("piece_choice") and not context.get("follow_up"): statements["guided_question"] = state["question"]
        if context.get("missing_topic"):
            statements["clarify_follow_up"] = "Hvilket træk eller hvilken idé vil du gerne have forklaret?" if language == "da" else "Which move or idea would you like me to explain?"
        for insight in strategic_insights(board, context.get("learner_color", "white" if board.turn else "black") == "white",
                context["preferences"].get("complexity", "beginner"), language):
            # A pawn-contact suggestion is a concrete move; keep it out of spoiler-protected catalogs.
            if insight["id"] == "strategy_pawn_breaks" and not reveal: continue
            statements[insight["id"]] = insight["text"]
        for index, candidate in enumerate(visible_candidates(context, reveal)):
            plan = candidate_strategy(board, candidate, language, context["preferences"].get("complexity", "beginner"))
            for effect_index, effect in enumerate(plan["effects"][:3]):
                statements[f"strategy_candidate_{index}_{effect_index}"] = effect["text"]
        priorities = context.get("game", {}).get("learning_profile", {}).get("concepts", [])
        if priorities:
            item = priorities[0]
            labels = {"forks": ("forks", "gafler"), "pins": ("pins", "bindinger"), "skewers": ("skewers", "spidninger"),
                "opening": ("opening decisions", "åbningsbeslutninger"), "middlegame": ("middlegame decisions", "midtspilsbeslutninger"),
                "endgame": ("endgame decisions", "slutspilsbeslutninger"), "defense": ("opponent threats", "modstanderens trusler"),
                "forcing_moves": ("checks and captures", "skakker og slag"), "safety": ("piece and king safety", "brik- og kongesikkerhed"),
                "exchanges": ("exchanges", "afbytninger"), "plans": ("planning", "planlægning")}
            label = labels.get(item["topic"], (item["topic"].replace("_", " "), item["topic"].replace("_", " ")))[language == "da"]
            if item["status"] in ("recurring_weakness", "emerging_weakness", "declining"):
                statements["learning_focus"] = (f"Dine observerede selvstændige valg i {item['games']} partier peger på {label} som et øveområde. Brug den aktuelle stillings verificerede oplysninger til at undersøge modstanderens svar; det fastslår ikke, hvad du tænkte." if language == "da" else
                    f"Observed independent decisions across {item['games']} games suggest practicing {label}. Use the verified evidence in this position to examine the opponent's replies; this does not establish what you were thinking.")
        return statements

    @staticmethod
    def validate_selection(selection: Selection, statements: dict, board: chess.Board, context: dict, reveal: bool) -> None:
        if any(key not in statements for key in selection.fact_ids): raise ValueError("Unsupported coaching statement")
        if not selection.response.strip() and not selection.fact_ids and not selection.segments: raise ValueError("Empty coaching response")
        grounded_response(selection, statements, "en")
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
        deadline = asyncio.get_running_loop().time() + 2
        # A cancelled to_thread semaphore waiter can acquire later and leak the
        # slot forever. Poll without blocking so cancellation leaves no waiter.
        while not self._slots.acquire(blocking=False):
            if asyncio.get_running_loop().time() >= deadline: raise ModelUnavailable("busy")
            await asyncio.sleep(.02)
        try:
            instruction = (
                "You are a patient chess teacher. All chess facts are supplied by a verified engine and legal board tools. "
                "Answer the user's actual question by composing grounded explanation segments from the dynamically generated "
                "statement catalog. Choose relevant evidence and order it into a clear explanation; avoid unrelated generic advice. "
                "Every segment must reference a fact_id in the catalog with framing plain, notice, or consider. "
                "An optional paraphrase may replace an evidence sentence with meaning-preserving wording. Preserve ALL claims, "
                "moves, squares, numbers, negations and uncertainty qualifications. Approved equivalents include attacked/under attack, "
                "legal/permitted, immediately/straight away, consider/think about, and this specific line/this particular variation. "
                "You may add harmless framing such as 'Here is the key observation: '. Never infer a cause from an engine ranking. "
                "Return only 2 to 4 relevant segments, usually enough to answer directly. Omit response, fact_ids, candidate_uci, "
                "pv_uci and tone; their defaults are safe and all board visuals are generated server-side from verified evidence. "
                "Do not copy a principal variation into the JSON. Never write unchecked prose in response; omit response entirely. "
                "Each segment should contain ONLY fact_id and framing. Do not include a text field or copy any sentence: the application "
                "renders the cited sentence itself. This keeps your JSON short and accurate. "
                "If evidence is insufficient select uncertainty. "
                "Only reference candidate "
                "moves and PVs supplied in the verified context. General principles are suggestions, and geometric attacks do not "
                "prove a profitable capture. Return ONLY JSON, for example "
                '{"segments":[{"fact_id":"plan","framing":"consider"}]}. '
                "Use question tone for Socratic coaching."
            )
            focused_follow_up = bool(context.get("follow_up") and context.get("piece_choice"))
            if focused_follow_up:
                instruction += (
                    " This is a follow-up about the recommendation in follow_up_focus. The supplied piece_choice_why "
                    "and impact statements explain that move. Focus on that idea; choose at most two relevant references "
                    "without selecting a new move."
                )
            reveal = reveal_requested(context) or not context.get("preferences", {}).get("hide_best_moves", True) if "question" in context else False
            line_allowed = show_line(context) if context.get("preferences") and "question" in context else False
            allowed_uci = {candidate["uci"] for candidate in visible_candidates(context, reveal)} if context.get("preferences") and "question" in context else set()
            compact_keys = ("uci", "san", "cp", "mate", "depth") + (("pv", "pv_uci") if line_allowed else ())
            compact_candidate = lambda candidate: {key: candidate[key] for key in compact_keys if key in candidate}
            analysis = context.get("analysis", {})
            game = context.get("game", {})
            last = game.get("last_player_decision") or {}
            feedback = last.get("feedback") or {}
            compact = {key: context[key] for key in ("fen", "learner_color", "side_to_move", "skill_level", "question") if key in context}
            if context.get("follow_up"):
                compact.update(question=context["user_question"], follow_up_to=context["question"])
                focus = context.get("topic_focus") or choice_recommendation(context)
                if focus: compact["follow_up_focus"] = {key: focus[key] for key in ("uci", "san")}
            compact["learning_profile"] = game.get("learning_profile", {})
            compact.update(legal_moves=context.get("legal_moves", []),
                history=[{"role": message["role"], "content": message["content"][-400:]} for message in context.get("history", [])[-4:]],
                requested_candidates=[compact_candidate(candidate) for candidate in context.get("requested_candidates", [])[:2]],
                analysis={"fen": analysis.get("fen"), "source": analysis.get("source"), "perspective": analysis.get("perspective"),
                          "candidates": [compact_candidate(candidate) for candidate in analysis.get("candidates", []) if candidate["uci"] in allowed_uci][:3]},
                game={"player_color": game.get("player_color"), "mode": game.get("mode"), "assessment_counts": game.get("assessment_counts", {}),
                      "last_player_decision": {"san": last.get("san"), "uci": last.get("uci"), "before_fen": last.get("before_fen"),
                          "classification": feedback.get("classification"), "consequence": feedback.get("consequence", "")[:500]}},
                coaching_state={key: value for key, value in context.get("coaching_state", {}).items()
                                if key in ("stage", "mode", "question", "acknowledgement", "discovered_ids")},
                disclosure={"candidate_moves": reveal, "variations": line_allowed and reveal})
            # Keep provider prefill bounded; full evidence remains server-side for validation.
            initial_keys = fallback_keys(context, statements, reveal_requested(context) or not context["preferences"].get("hide_best_moves", True)) if context.get("preferences") and "question" in context else []
            prioritized = list(dict.fromkeys((["learning_focus"] if "learning_focus" in statements else []) + initial_keys +
                [key for key in statements if key.startswith(("discovery_", "guided_", "strategy_candidate_0"))] + list(statements)))
            catalog, catalog_size = {}, 0
            for key in prioritized:
                if key not in statements: continue
                if focused_follow_up and not (key.startswith(("piece_choice_", "impact_", "outcome_", "motif_")) or key in (
                        "terminal", "check", "turn", "clarify_move", "clarify_follow_up", "uncertainty", "offline")):
                    continue
                size = len(key) + len(statements[key])
                if catalog_size + size > 7000 or len(catalog) >= 18: continue
                catalog[key] = statements[key]
                catalog_size += size
            payload = {"model": llm.model, "messages": [{"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps({"verified_context": compact, "statement_catalog": catalog})}],
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
        if "guided_question" in statements:
            if "discovery_acknowledgement" in statements: keys.insert(0, "discovery_acknowledgement")
            if not reveal and not any(key in keys for key in ("previous_assessment", "terminal", "clarify_move")):
                keys = [key for key in ("discovery_acknowledgement", "guided_question") if key in statements]
            else: keys = [key for key in keys if key not in ("habit", "question")] + ["guided_question"]
        topic_terms = {"pawn": ("pawn", "bonde", "structure", "struktur"), "king_safety": ("king safety", "kongens sikker"),
                       "activity": ("activity", "aktivitet"), "outposts": ("outpost", "forpost"),
                       "space": ("space", "plads"), "open_files": ("open file", "åben linje"),
                       "pawn_breaks": ("pawn break", "bondestød")}
        question = context["question"].lower()
        if "learning_focus" in statements and any(term in question for term in ("thinking", "focus", "practice", "learn", "tænke", "øve", "lære")):
            keys = ["learning_focus", *keys]
        strategic_keys = [key for key in statements if key.startswith("strategy_") and not key.startswith("strategy_candidate")]
        requested_strategy = any(term in question for terms in topic_terms.values() for term in terms)
        if requested_strategy or "plan" in question:
            chosen = strategic_keys if "plan" in question else [key for key in strategic_keys if
                any(term in question for term in topic_terms.get(key.removeprefix("strategy_"), topic_terms["pawn"]))]
            keys = [key for key in keys if key not in ("habit", "plan")] + chosen[:3]
        if reveal and preferences.get("complexity") == "advanced":
            keys += [key for key in statements if key.startswith("strategy_candidate_0_")][:2]
        source = "deterministic"
        fallback_reason = None
        try:
            # Total deadline also bounds servers that send tiny deltas indefinitely.
            request = self._model_selection(context, statements, llm) if llm is not None else self._model_selection(context, statements)
            selection = await asyncio.wait_for(request, timeout=settings.llm_timeout + 2)
            corrected = False
            if selection.segments and selection.response.strip():
                # Real providers sometimes emit redundant prose despite the schema instructions.
                # Discard every unchecked character; only validated structured claims can reach the user.
                selection.response = ""
                corrected = True
            if not reveal and selection.candidate_uci is not None:
                selection.candidate_uci = None
                corrected = True
            if (not reveal or not show_line(context)) and selection.pv_uci:
                selection.pv_uci = []
                corrected = True
            for segment in selection.segments:
                if segment.paraphrase and segment.fact_id in statements:
                    try: verified_paraphrase(segment.paraphrase, statements[segment.fact_id])
                    except ValueError:
                        # Keep the selected verified claim, replacing only the unsupported wording.
                        segment.paraphrase = None
                        corrected = True
            self.validate_selection(selection, statements, board, context, reveal)
            mandatory = [key for key in ("terminal", "clarify_move", "outcome_0") if key in statements]
            if "clarify_follow_up" in statements: mandatory = ["clarify_follow_up"]
            if "piece_choice_answer" in statements:
                mandatory = [key for key in ("terminal", "turn", "check") if key in statements]
                mandatory += [key for key in statements if key.startswith("piece_choice_")]
            elif context.get("follow_up"):
                mandatory = [key for key in keys if key not in ("habit", "question", "plan")]
            if "guided_question" in statements:
                mandatory += [key for key in ("discovery_acknowledgement", "guided_question") if key in statements]
            question = context["question"].lower()
            if any(term in question for term in ("last move", "previous move", "why was", "sidste træk")):
                mandatory += [key for key in ("previous_assessment", "previous_reason", "previous_consequence") if key in statements]
            composed = grounded_response(selection, statements, language)
            if composed and "review" not in statements and not mandatory:
                max_words = preferences.get("max_explanation_length", 120)
                # Preserve complete statements and their qualifications rather than truncating factual sentences.
                text = composed if len(composed.split()) <= max_words else " ".join(
                    statements[segment.fact_id] for segment in selection.segments[:2]) or composed
                context["response_fact_ids"] = [segment.fact_id for segment in selection.segments] or selection.fact_ids
                return text, "local_llm_grounded_corrected" if corrected else "local_llm_verified", None
            keys = list(dict.fromkeys(mandatory + [segment.fact_id for segment in selection.segments] + selection.fact_ids))
            if "clarify_follow_up" in statements:
                keys = ["clarify_follow_up"]
            elif "piece_choice_answer" in statements:
                keys = [key for key in keys if key in mandatory or key.startswith(("outcome_", "impact_"))]
            if "review" in statements:
                keys = list(dict.fromkeys([key for key in ("review", "previous_assessment") if key in statements] + keys))
            source = "local_llm_grounded_corrected" if corrected else "local_llm_verified"
        except (RuntimeError, ValueError, httpx.HTTPError, asyncio.TimeoutError, KeyError, TypeError) as error:
            fallback_reason = model_failure_reason(error)
        max_words = preferences.get("max_explanation_length", 120)
        selected, count = [], 0
        for key in keys:
            sentence = statements[key]
            if selected and count + len(sentence.split()) > max_words: break
            selected.append(sentence)
            count += len(sentence.split())
        context["response_fact_ids"] = keys[:len(selected)]
        return " ".join(selected), source, fallback_reason

    def visual_evidence(self, board: chess.Board, context: dict, language: str) -> dict:
        if context.get("missing_topic"): return {"insights": [], "variations": [], "ambiguous_moves": []}
        reveal = reveal_requested(context) or not context["preferences"].get("hide_best_moves", True)
        insights, variations = [], []
        if context.get("piece_choice"):
            choices = list(context.get("requested_candidates", [])) if reveal else []
            priority = choice_recommendation(context) if reveal else None
            if priority and all(candidate["uci"] != priority["uci"] for candidate in choices): choices.insert(0, priority)
            statements = piece_choice_statements(board, context, language, reveal)
            for candidate in choices:
                items, lines = move_insights(board, candidate, language)
                index = next((i for i, compared in enumerate(context.get("requested_candidates", [])) if compared["uci"] == candidate["uci"]), None)
                insights.append({**items[0], "text": statements.get(f"piece_choice_{index}", items[0]["text"])})
                if show_line(context): variations.extend(lines)
            if not insights:
                request = context["piece_choice"]
                sources = sorted({chess.square_name(move.from_square) for piece in request["pieces"]
                                  for move in choice_moves(board, piece, request["development"])}) if context["learner_color"] == ("white" if board.turn else "black") else []
                if sources:
                    insights.append({"id": "piece_choice_sources", "fen": board.fen(), "claim_type": "legal_move",
                        "text": "Sammenlign disse brikkers udvikling." if language == "da" else "Compare the development of these pieces.",
                        "squares": sources, "arrows": []})
            return {"insights": insights, "variations": variations, "ambiguous_moves": context.get("ambiguous_moves", [])}
        for candidate in visible_candidates(context, reveal):
            items, lines = move_insights(board, candidate, language)
            insights.extend(items)
            insights.extend(candidate_strategy(board, candidate, language, context["preferences"].get("complexity", "beginner"))["effects"])
            if show_line(context): variations.extend(lines)
        for insight in strategic_insights(board, context.get("learner_color", "white" if board.turn else "black") == "white", context["preferences"].get("complexity", "beginner"), language):
            if insight["id"] != "strategy_pawn_breaks" or reveal: insights.append(insight)
        return {"insights": insights, "variations": variations, "ambiguous_moves": context.get("ambiguous_moves", [])}

    def hint(self, board: chess.Board, level: int, language: str = "en", time_ms: int = 250, depth: int | None = None, candidates: int = 3, question: str = "", topic: dict | None = None) -> dict:
        if level not in (1, 2): raise ValueError("Choose hint 1 or 2")
        analysis = engine_service.analyze(board, candidates=candidates, time_ms=time_ms, depth=depth)
        if question or topic:
            context = self.context(board, {}, question, [], analysis=analysis, topic=topic)
            priority = choice_recommendation(context)
            if not context.get("piece_choice"):
                priority = context.get("topic_focus") or next(iter(context.get("requested_candidates", [])), None)
            if priority:
                analysis = {**analysis, "candidates": [priority]}
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
                text = "Undersøg først dine lovlige skakker og modstanderens svar." if da else "Start by examining your legal checks and the opponent's replies."
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
                text = ("Undersøg først modstanderens trusler, og find derefter en brik at forbedre." if da else
                        "First check the opponent's threats, then look for a piece you can improve.")
        elif level == 2:
            if facts["check"] and target:
                text = (f"Din {piece} på {facts['from']} kan give skak og samtidig angribe modstanderens {target_piece} på {target}." if da else
                        f"Your {piece} on {facts['from']} can give check while also attacking the opponent's {target_piece} on {target}.")
            elif facts["check"]:
                text = (f"Fokuser på din {piece} på {facts['from']}; den stærkeste idé begynder med skak." if da else
                        f"Focus on your {piece} on {facts['from']}; the strongest idea starts with a check.")
            elif facts["capture"]:
                captured = piece_names.get(facts.get("captured_piece"), "brik") if da else (facts.get("captured_piece") or "piece")
                text = (f"Fokuser på din {piece} på {facts['from']}: undersøg dens slag og mulige genslag." if da else
                        f"Focus on your {piece} on {facts['from']}: examine its captures and possible recaptures.")
            elif facts["castle"]:
                text = (f"Undersøg rokade med kongen på {facts['from']}; sammenlign kongens sikkerhed før og efter." if da else
                        f"Consider castling with the king on {facts['from']}; compare king safety before and after.")
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
            text += (f" Undersøg {facts['from']} → {facts['to']} på brættet, og overvej modstanderens svar." if da else
                     f" Examine {facts['from']} → {facts['to']} on the board and consider the opponent's reply.")
        side = ("Hvid" if board.turn else "Sort") if da else ("White" if board.turn else "Black")
        text = (f"{side} i trækket: " if da else f"{side} to move: ") + text
        result = {"fen": board.fen(), "level": level, "text": text, "perspective": "white" if board.turn else "black"}
        if level == 1:
            result["highlight_square"] = chess.square_name(move.from_square)
        if level >= 2:
            result["highlight_move"] = best["uci"]
        return result


coach_service = CoachService()
