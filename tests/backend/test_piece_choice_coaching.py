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


@pytest.mark.parametrize("follow_up", ["Why?", "Why is that?", "Hvorfor?", "Uddyb", "Show me"])
def test_short_follow_up_retains_the_previous_piece_choice(position, monkeypatch, follow_up):
    board, _ = position
    service = CoachService()
    async def offline(*_args): raise ModelUnavailable("not_configured")
    monkeypatch.setattr(service, "_model_selection", offline)
    history = [{"role": "user", "content": "Should I develop the knight or bishop first?"},
               {"role": "assistant", "content": "Start with your knight: Nf3."}]
    context = service.context(board, Preferences().model_dump(), follow_up, history)
    assert context["piece_choice"] is not None
    text, _, _ = asyncio.run(service.respond(board, context, "en"))
    assert "Nf3" in text and "bishop" in text
    assert service.visual_evidence(board, context, "en")["insights"][0]["arrows"][0]["from"] == "g1"


def test_persisted_follow_up_and_hints_keep_the_original_recommendation(position, signed, monkeypatch):
    from src.backend.coach import coach_service
    board, scores = position
    async def offline(*_args): raise ModelUnavailable("not_configured")
    monkeypatch.setattr(coach_service, "_model_selection", offline)
    game = signed.post("/api/games", json={"mode": "analysis", "fen": board.fen()}).json()
    base = {"game_id": game["id"], "revision": game["revision"], "fen": board.fen(), "language": "en"}
    first = signed.post("/api/coach", json={**base, "question": "Should I develop my knight or bishop first?"})
    assert "Nf3" in first.text
    # Follow-up requests must explain the recommendation already made, even if
    # a fresh, short search would now slightly reorder the alternatives.
    scores.update(g1f3=10, f1c4=30)
    for question in ("Why?", "Explain more"):
        reply = signed.post("/api/coach", json={**base, "question": question})
        done = json.loads(reply.text.split("event: done\ndata: ")[1].splitlines()[0])
        assert done["hint_question"] == "Should I develop my knight or bishop first?"
        assert done["insights"][0]["arrows"][0] == {"from": "g1", "to": "f3", "color": "green"}
        assert "Nf3" in done["text"] and "d4" in done["text"]
    hint = signed.post("/api/hint", json={"game_id": game["id"], "fen": board.fen(), "question": "Why?", "level": 2})
    assert hint.status_code == 200, hint.text
    assert hint.json()["highlight_move"] == "g1f3"


def test_follow_up_does_not_restore_a_different_position_or_override_a_new_topic(position):
    from src.backend.coaching_conversation import topic_snapshot
    from src.backend.coaching_choices import choice_recommendation
    board, _ = position
    service = CoachService()
    initial = service.context(board, Preferences().model_dump(), "Knight or bishop first?", [])
    topic = topic_snapshot(initial, choice_recommendation(initial))
    new_topic = service.context(board, Preferences().model_dump(), "Can I castle?", [], topic=topic)
    assert new_topic["piece_choice"] is None and new_topic["question"] == "Can I castle?"
    changed = board.copy()
    changed.push_uci("g1f3")
    follow_up = service.context(changed, Preferences().model_dump(), "Why?", [{"role": "user", "content": topic["question"], "fen": board.fen()}], topic=topic)
    assert follow_up["missing_topic"] and not follow_up["piece_choice"]
    assert not follow_up["requested_candidates"]


def test_a_question_remains_in_the_timeline_if_explanation_is_interrupted(position, signed, monkeypatch):
    from src.backend.coach import coach_service
    board, _ = position
    game = signed.post("/api/games", json={"mode": "analysis", "fen": board.fen()}).json()
    def failed(*_args, **_kwargs): raise ValueError("interrupted context")
    monkeypatch.setattr(coach_service, "context", failed)
    response = signed.post("/api/coach", json={"game_id": game["id"], "revision": 0, "fen": board.fen(), "question": "Knight or bishop first?"})
    assert "event: error" in response.text
    timeline = signed.get(f"/api/games/{game['id']}/conversation?timeline=true").json()["messages"]
    assert len(timeline) == 1 and timeline[0]["role"] == "user"
    assert timeline[0]["content"] == "Knight or bishop first?" and timeline[0]["ply"] == 0


def test_historical_follow_up_is_ordered_at_the_time_it_was_asked(position, signed, monkeypatch):
    from src.backend.coach import coach_service
    board, _ = position
    async def offline(*_args): raise ModelUnavailable("not_configured")
    monkeypatch.setattr(coach_service, "_model_selection", offline)
    monkeypatch.setattr(engine_service, "grade", lambda board, move, **_kwargs: {"fen": board.fen(), "text": "Verified move.", "classification": "Good"})
    game = signed.post("/api/games", json={"mode": "analysis", "fen": board.fen()}).json()
    base = {"game_id": game["id"], "fen": board.fen(), "language": "en"}
    signed.post("/api/coach", json={**base, "revision": 0, "question": "Knight or bishop first?"})
    moved = signed.post(f"/api/games/{game['id']}/moves", json={"revision": 0, "move": "g1f3"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["moves"][0]["timeline_revision"] == 1
    reply = signed.post("/api/coach", json={**base, "revision": 1, "question": "Why?"})
    done = json.loads(reply.text.split("event: done\ndata: ")[1].splitlines()[0])
    assert done["ply"] == 0 and done["timeline_revision"] == 1
    timeline = signed.get(f"/api/games/{game['id']}/conversation?timeline=true").json()["messages"]
    assert [message["timeline_revision"] for message in timeline] == [0, 0, 1, 1]
    assert [message["role"] for message in timeline] == ["user", "assistant", "user", "assistant"]
    assert not signed.get(f"/api/games/{game['id']}/conversation").json()["messages"]


def test_unanchored_why_requests_clarification_without_unrelated_board_hints(position, monkeypatch):
    board, _ = position
    service = CoachService()
    async def generic(*_args): return Selection(fact_ids=["plan"])
    monkeypatch.setattr(service, "_model_selection", generic)
    context = service.context(board, Preferences().model_dump(), "Why?", [])
    text, _, _ = asyncio.run(service.respond(board, context, "en"))
    assert text == "Which move or idea would you like me to explain?"
    assert not service.visual_evidence(board, context, "en")["insights"]


def test_model_follow_up_receives_the_pinned_move_and_focused_explanation_evidence(position, monkeypatch):
    import httpx
    from src.backend.coaching_choices import choice_recommendation
    from src.backend.coaching_conversation import topic_snapshot
    from src.backend.llm_settings import Connection
    board, _ = position
    service = CoachService()
    question = "Should I develop my knight or bishop first?"
    initial = service.context(board, Preferences().model_dump(), question, [])
    context = service.context(board, Preferences().model_dump(), "Why?", [], topic=topic_snapshot(initial, choice_recommendation(initial)))
    original = httpx.AsyncClient
    def provider(request):
        payload = json.loads(request.content)
        prompt = json.loads(payload["messages"][1]["content"])
        assert prompt["verified_context"]["question"] == "Why?"
        assert prompt["verified_context"]["follow_up_focus"]["uci"] == "g1f3"
        assert prompt["verified_context"]["follow_up_to"] == question
        assert "piece_choice_why" in prompt["statement_catalog"]
        assert "castle" not in prompt["statement_catalog"] and "plan" not in prompt["statement_catalog"]
        event = {"choices": [{"delta": {"content": '{"fact_ids":["piece_choice_why"]}'}}]}
        return httpx.Response(200, text=f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(provider), **kwargs))
    statements = service.statements(board, context, "en", True)
    selection = asyncio.run(service._model_selection(context, statements, Connection("http://provider.test/v1", "reasoning-model")))
    assert selection.fact_ids == ["piece_choice_why"]
