import asyncio

import chess
import httpx
import pytest

from src.backend.coach import CoachService, Selection, ModelUnavailable, model_failure_reason
from src.backend.schemas import Preferences


def context():
    board = chess.Board()
    evidence = {"fen": board.fen(), "candidates": [{"uci": "e2e4", "san": "e4", "pv_uci": ["e2e4", "e7e5"], "pv": ["e4", "e5"]}]}
    return board, {"fen": board.fen(), "analysis": evidence, "requested_candidates": [], "question": "Help me learn", "preferences": Preferences().model_dump()}


def test_reject_invented_fact_illegal_move_and_unverified_variation():
    service = CoachService()
    board, ctx = context()
    statements = {"plan": "Develop your pieces"}
    ctx["question"] = "Show the best moves"
    ctx["preferences"]["show_pv"] = True
    for selection in [Selection(fact_ids=["invented_mate"]), Selection(fact_ids=["plan"], candidate_uci="e2e5"),
                      Selection(fact_ids=["plan"], pv_uci=["e2e4", "e7e6"])]:
        with pytest.raises(ValueError): service.validate_selection(selection, statements, board, ctx, True)
    service.validate_selection(Selection(fact_ids=["plan"], candidate_uci="e2e4", pv_uci=["e2e4", "e7e5"]), statements, board, ctx, True)
    with pytest.raises(ValueError): service.validate_selection(Selection(fact_ids=["plan"], candidate_uci="e2e4"), statements, board, ctx, False)


@pytest.mark.parametrize("failure", [ValueError("malformed JSON"), httpx.ReadTimeout("timeout"), RuntimeError("offline")])
def test_bad_model_responses_fall_back(monkeypatch, failure):
    service = CoachService()
    board, ctx = context()
    async def failed(*_args): raise failure
    monkeypatch.setattr(service, "_model_selection", failed)
    text, source, reason = asyncio.run(service.respond(board, ctx, "en"))
    assert source == "deterministic" and "center" in text
    assert "e4:" not in text


def test_selected_verified_fact_and_danish(monkeypatch):
    service = CoachService()
    board, ctx = context()
    async def selected(*_args): return Selection(fact_ids=["plan", "habit"])
    monkeypatch.setattr(service, "_model_selection", selected)
    text, source, reason = asyncio.run(service.respond(board, ctx, "da"))
    assert source == "local_llm_verified" and reason is None
    assert "centrum" in text and "Before moving" not in text


@pytest.mark.parametrize("completion,expected_source", [
    ('{"fact_ids":["plan"],"candidate_uci":null,"pv_uci":[],"tone":"explain"}', "local_llm_verified"),
    ('{"fact_ids":["made_up_mate"]}', "deterministic"),
    ('{"fact_ids":["plan"],"unverified_explanation":"Win the queen"}', "deterministic"),
    ('not valid JSON', "deterministic"),
])
def test_openai_compatible_stream_is_buffered_and_validated(monkeypatch, completion, expected_source):
    import json
    from dataclasses import replace
    import src.backend.coach as coach
    original = httpx.AsyncClient
    requests = []
    def handler(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["model"] == "local-test-model" and payload["stream"] is True
        assert request.headers["authorization"] == "Bearer local-test-secret"
        fragments = [completion[:10], completion[10:]]
        content = "".join("data: " + json.dumps({"choices": [{"delta": {"content": value}}]}) + "\n\n" for value in fragments)
        return httpx.Response(200, text=content + "data: [DONE]\n\n", headers={"content-type": "text/event-stream"})
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(coach.httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    monkeypatch.setattr(coach, "settings", replace(coach.settings, llm_base_url="http://local-model.test/v1", llm_model="local-test-model", llm_api_key="local-test-secret"))
    board, ctx = context()
    text, source, reason = asyncio.run(CoachService().respond(board, ctx, "en"))
    assert source == expected_source
    assert reason == (None if expected_source == "local_llm_verified" else "invalid_response")
    assert "made_up_mate" not in text and "Win the queen" not in text
    assert requests[0].url.path == "/v1/chat/completions"


def test_explicit_candidate_question_reveals_requested_move_only():
    service = CoachService()
    board = chess.Board()
    ctx = service.context(board, Preferences().model_dump(), "What if Nf3?", [])
    text, source, reason = asyncio.run(service.respond(board, ctx, "en"))
    assert "Nf3:" in text and "continuation" in text
    assert "e4:" not in text and "d4:" not in text


def test_castling_question_is_grounded_in_legal_routes():
    service = CoachService()
    board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    ctx = service.context(board, Preferences().model_dump(), "Should I castle now?", [])
    text, _, _ = asyncio.run(service.respond(board, ctx, "en"))
    assert "Castling is legal" in text and "O-O" in text
    board = chess.Board()
    ctx = service.context(board, Preferences().model_dump(), "Should I castle now?", [])
    text, _, _ = asyncio.run(service.respond(board, ctx, "en"))
    assert "not legal" in text and "f1" in text


def test_piece_comparison_finds_only_available_piece_moves():
    service = CoachService()
    board = chess.Board()
    ctx = service.context(board, Preferences().model_dump(), "Is moving my knight better than my bishop?", [])
    assert ctx["requested_candidates"][0]["facts"]["piece"] == "knight"
    text, _, _ = asyncio.run(service.respond(board, ctx, "en"))
    assert "no legal move with your bishop" in text


@pytest.mark.parametrize("failure,expected", [
    (ModelUnavailable("not_configured"), "not_configured"),
    (ModelUnavailable("busy"), "busy"),
    (httpx.ReadTimeout("private endpoint"), "timeout"),
    (httpx.ConnectError("private endpoint"), "connection"),
    (ValueError("private model output"), "invalid_response"),
])
def test_fallback_reason_does_not_expose_provider_details(monkeypatch, failure, expected):
    service = CoachService()
    board, ctx = context()
    async def failed(*_args): raise failure
    monkeypatch.setattr(service, "_model_selection", failed)
    text, source, reason = asyncio.run(service.respond(board, ctx, "en"))
    assert source == "deterministic" and reason == expected
    assert "private" not in text


@pytest.mark.parametrize("status,expected", [(401, "authentication"), (403, "authentication"), (404, "server_error"), (500, "server_error")])
def test_model_http_failures_are_classified(status, expected):
    response = httpx.Response(status, request=httpx.Request("POST", "http://private.test/v1/chat/completions"))
    assert model_failure_reason(httpx.HTTPStatusError("private response", request=response.request, response=response)) == expected


def test_tls_failure_is_distinct_from_connection_failure():
    import ssl
    error = httpx.ConnectError("private endpoint")
    error.__cause__ = ssl.SSLCertVerificationError("certificate failed")
    assert model_failure_reason(error) == "tls_certificate"


def test_model_selection_keeps_requested_review_summary(monkeypatch):
    service = CoachService()
    board, ctx = context()
    ctx["question"] = "How have my moves been so far?"
    ctx["game"] = {"assessment_counts": {"Good": 2, "Mistake": 1}}
    async def selected(*_args): return Selection(fact_ids=["plan"])
    monkeypatch.setattr(service, "_model_selection", selected)
    text, source, reason = asyncio.run(service.respond(board, ctx, "en"))
    assert "Reviewed 3 of your moves" in text and "2 Good, 1 Mistake" in text
    assert source == "local_llm_verified" and reason is None


@pytest.mark.parametrize("effort,expected_source", [("", "deterministic"), ("none", "local_llm_verified")])
def test_reasoning_model_can_reserve_its_budget_for_verified_json(monkeypatch, effort, expected_source):
    import json
    from dataclasses import replace
    import src.backend.coach as coach
    original = httpx.AsyncClient
    def model(request):
        payload = json.loads(request.content)
        if effort:
            assert payload["reasoning_effort"] == effort
            delta, finish = {"content": '{"fact_ids":["plan"]}'}, "stop"
        else:
            assert "reasoning_effort" not in payload
            # A reasoning model can exhaust max_tokens without emitting any final JSON.
            delta, finish = {"reasoning_content": "Selecting a fact..."}, "length"
        content = json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]})
        return httpx.Response(200, text=f"data: {content}\n\ndata: [DONE]\n\n")
    monkeypatch.setattr(coach, "settings", replace(coach.settings, llm_reasoning_effort=effort,
        llm_base_url="http://model.test/v1", llm_model="reasoning-model"))
    monkeypatch.setattr(coach.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(model), **kwargs))
    board, ctx = context()
    text, source, reason = asyncio.run(CoachService().respond(board, ctx, "en"))
    assert source == expected_source
    assert "center" in text
    assert reason == (None if effort else "invalid_response")
