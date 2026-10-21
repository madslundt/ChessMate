import asyncio
import json

import chess
import pytest

from src.backend.chess_tools import move_facts, observations
from src.backend.coach import CoachService, ModelUnavailable, Selection
from src.backend.coaching_state import advance_discovery
from src.backend.engine import EngineUnavailable, engine_service
from src.backend.schemas import Preferences


SPOKEN_QUESTION = "Så nu har jeg overtaget midten så hvad vil det næste jeg tænker det vil være at udvikle mine brikker men hvem skal jeg udvikle først er det hesten eller løberen eller løberen eller springeren hvad er det"


@pytest.fixture
def position(monkeypatch):
    board = chess.Board()
    for move in ("e2e4", "e7e5"):
        board.push_uci(move)
    scores = {"g1f3": 70, "f1c4": 20}
    def analyze(board, root_moves=None, **_kwargs):
        choices = root_moves or list(board.legal_moves)
        move = max(choices, key=lambda move: scores.get(move.uci(), -20))
        candidate = {"uci": move.uci(), "san": board.san(move), "cp": scores.get(move.uci(), -20),
                     "mate": None, "pv_uci": [move.uci()], "pv": [board.san(move)], "facts": move_facts(board, move)}
        return {"fen": board.fen(), "candidates": [candidate], "source": "stockfish", "observations": observations(board)}
    monkeypatch.setattr(engine_service, "analyze", analyze)
    return board, scores


@pytest.mark.parametrize("question", [SPOKEN_QUESTION, "Should I develop my knight or bishop first?", "Springer eller løber først?", "Which piece should I develop next?"])
def test_natural_development_questions_analyze_both_piece_choices(position, question):
    board, _ = position
    context = CoachService().context(board, Preferences().model_dump(), question, [])
    assert {candidate["facts"]["piece"] for candidate in context["requested_candidates"]} == {"knight", "bishop"}


def test_reviewing_a_past_development_move_does_not_request_a_new_piece_choice(position):
    board, _ = position
    context = CoachService().context(board, Preferences().model_dump(), "Why was developing my knight a mistake?", [])
    assert context["piece_choice"] is None


@pytest.mark.parametrize("model_available", [False, True])
def test_guided_coach_answers_piece_choice_before_generic_advice(position, monkeypatch, model_available):
    board, _ = position
    service = CoachService()
    async def model(*_args):
        if not model_available:
            raise ModelUnavailable("not_configured")
        return Selection(fact_ids=["plan", "castle", "question"])
    monkeypatch.setattr(service, "_model_selection", model)
    context = service.context(board, Preferences().model_dump(), SPOKEN_QUESTION, [])
    context["coaching_state"] = advance_discovery(board, context, None, "guided", "da")
    text, _, _ = asyncio.run(service.respond(board, context, "da"))
    assert "springer" in text and "løber" in text and "Nf3" in text and "Bc4" in text
    assert text.index("springer") < text.index("løber")
    assert "Rokade er ikke lovlig" not in text and "skakker og slag bør" not in text
    assert "piece_choice_answer" in context["response_fact_ids"]
    visuals = service.visual_evidence(board, context, "da")
    assert {insight["arrows"][0]["from"] for insight in visuals["insights"] if insight["id"].startswith("move_") and insight["fen"] == board.fen() and insight["arrows"]} >= {"g1", "f1"}


def test_piece_choice_follows_the_position_instead_of_always_recommending_knights(position, monkeypatch):
    board, scores = position
    scores.update(g1f3=10, f1c4=90)
    service = CoachService()
    async def offline(*_args): raise ModelUnavailable("not_configured")
    monkeypatch.setattr(service, "_model_selection", offline)
    context = service.context(board, Preferences().model_dump(), "Knight or bishop first?", [])
    text, _, _ = asyncio.run(service.respond(board, context, "en"))
    assert "bishop" in text and text.index("Bc4") < text.index("Nf3")


def test_piece_choice_does_not_recommend_an_opponents_move(position):
    board, _ = position
    context = CoachService().context(board, Preferences().model_dump(), "Should I develop the knight or bishop first?", [], {"player_color": "black", "mode": "computer"})
    assert not context["requested_candidates"]


def test_explicit_no_spoilers_keeps_piece_choice_moves_off_the_board(position, monkeypatch):
    board, _ = position
    service = CoachService()
    async def offline(*_args): raise ModelUnavailable("not_configured")
    monkeypatch.setattr(service, "_model_selection", offline)
    context = service.context(board, Preferences().model_dump(), "Knight or bishop first, without revealing moves?", [])
    text, _, _ = asyncio.run(service.respond(board, context, "en"))
    assert "Nf3" not in text and "Bc4" not in text
    assert not any(insight["id"].startswith("move_") for insight in service.visual_evidence(board, context, "en")["insights"])


def test_engine_failure_does_not_turn_a_piece_choice_into_a_fabricated_ranking(position, monkeypatch):
    board, _ = position
    service = CoachService()
    def unavailable(*_args, **_kwargs): raise EngineUnavailable("offline")
    async def offline(*_args): raise ModelUnavailable("not_configured")
    monkeypatch.setattr(engine_service, "analyze", unavailable)
    monkeypatch.setattr(service, "_model_selection", offline)
    context = service.context(board, Preferences().model_dump(), "Knight or bishop first?", [])
    text, _, _ = asyncio.run(service.respond(board, context, "en"))
    assert "knight" in text and "bishop" in text
    assert "cannot rank" in text


def test_coach_reply_and_two_hints_share_the_piece_choice(position, signed, monkeypatch):
    from src.backend.coach import coach_service
    board, _ = position
    async def model(*_args): return Selection(fact_ids=["plan"])
    monkeypatch.setattr(coach_service, "_model_selection", model)
    response = signed.post("/api/coach", json={"fen": board.fen(), "question": SPOKEN_QUESTION, "language": "da", "teaching_mode": "guided"})
    assert response.status_code == 200, response.text
    done = json.loads(response.text.split("event: done\ndata: ")[1].splitlines()[0])
    assert "Nf3" in done["text"] and "Bc4" in done["text"]
    assert done["fen"] == board.fen() and "piece_choice_answer" in done["evidence_ids"]
    assert any(insight["arrows"] == [{"from": "g1", "to": "f3", "color": "green"}] for insight in done["insights"])
    for level in (1, 2):
        hint = signed.post("/api/hint", json={"fen": board.fen(), "question": SPOKEN_QUESTION, "level": level})
        assert hint.status_code == 200, hint.text
        assert hint.json().get("highlight_square") == ("g1" if level == 1 else None)
        assert hint.json().get("highlight_move") == ("g1f3" if level == 2 else None)
        assert not hint.json().get("candidates") and not hint.json().get("variations")
    generic = signed.post("/api/hint", json={"fen": board.fen(), "question": "Help me", "level": 1})
    assert generic.status_code == 200, generic.text


def test_equal_piece_options_are_not_presented_as_a_clear_engine_preference(position, monkeypatch):
    board, scores = position
    scores.update(g1f3=30, f1c4=25)
    service = CoachService()
    async def offline(*_args): raise ModelUnavailable("not_configured")
    monkeypatch.setattr(service, "_model_selection", offline)
    context = service.context(board, Preferences().model_dump(), "Knight or bishop first?", [])
    text, _, _ = asyncio.run(service.respond(board, context, "en"))
    assert "similarly" in text and "Nf3" in text and "Bc4" in text


def test_more_urgent_move_stays_aligned_with_the_board_and_hints(position, monkeypatch):
    board, scores = position
    scores["d2d4"] = 400
    service = CoachService()
    async def offline(*_args): raise ModelUnavailable("not_configured")
    monkeypatch.setattr(service, "_model_selection", offline)
    context = service.context(board, Preferences().model_dump(), "Knight or bishop first?", [])
    text, _, _ = asyncio.run(service.respond(board, context, "en"))
    assert "examine d4" in text
    visuals = service.visual_evidence(board, context, "en")
    assert visuals["insights"][0]["arrows"][0]["from"] == "d2"
    hint = service.hint(board, 2, question="Knight or bishop first?")
    assert hint["highlight_move"] == "d2d4"
