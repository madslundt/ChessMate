import json

import chess
import httpx
import pytest


CONNECTION = {"base_url": "http://model-server:8000/v1", "model": "local-chess-model"}


def test_connection_requires_authentication(client):
    assert client.get("/api/settings/llm").status_code == 401
    assert client.patch("/api/settings/llm", json=CONNECTION).status_code == 401


def test_save_preserve_remove_key_and_persist(signed):
    secret = "test-only-provider-secret"
    response = signed.patch("/api/settings/llm", json={**CONNECTION, "api_key": secret})
    assert response.status_code == 200
    assert response.json() == {**CONNECTION, "has_api_key": True, "configured": True}
    assert secret not in response.text
    assert secret not in signed.get("/api/settings/llm").text
    assert secret not in signed.get("/api/auth/me").text
    assert secret not in signed.get("/api/settings").text
    signed.post("/api/auth/logout", json={})
    signed.post("/api/auth/login", json={"name": "learner", "password": "test-passphrase"})
    assert signed.get("/api/settings/llm").json()["model"] == CONNECTION["model"]
    response = signed.patch("/api/settings/llm", json={**CONNECTION, "model": "another-model"})
    assert response.json()["has_api_key"] is True
    assert signed.patch("/api/settings/llm", json={**CONNECTION, "clear_api_key": True}).json()["has_api_key"] is False


def test_endpoint_change_cannot_forward_old_key_and_accounts_are_isolated(signed):
    signed.patch("/api/settings/llm", json={**CONNECTION, "api_key": "old-key"})
    changed = {**CONNECTION, "base_url": "http://different-server:8000/v1"}
    assert signed.patch("/api/settings/llm", json=changed).json()["has_api_key"] is False
    signed.post("/api/auth/logout", json={})
    signed.post("/api/auth/register", json={"name": "separate-account", "password": "another-passphrase"})
    assert signed.get("/api/settings/llm").json()["base_url"] != changed["base_url"]


@pytest.mark.parametrize("invalid", [
    {"base_url": "file:///etc/passwd", "model": "test"},
    {"base_url": "http://user:password@model/v1", "model": "test"},
    {"base_url": "http://model/v1?api_key=secret", "model": "test"},
    {"base_url": "http://model:999999/v1", "model": "test"},
    {"base_url": "http://model/v1", "model": ""},
    {"base_url": "", "model": "test"},
    {**CONNECTION, "api_key": "secret\ninvalid"},
    {**CONNECTION, "api_key": "secret", "clear_api_key": True},
])
def test_validation_never_echoes_input_or_secret(signed, invalid):
    response = signed.patch("/api/settings/llm", json=invalid)
    assert response.status_code == 422
    assert "secret" not in response.text and "password@" not in response.text
    assert '"input"' not in response.text


def test_saved_connection_drives_coaching_and_empty_connection_disables_it(signed, monkeypatch):
    requests = []
    def model(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["model"] == CONNECTION["model"]
        assert request.headers["Authorization"] == "Bearer fixture-key"
        assert "fixture-key" not in request.content.decode()
        content = json.dumps({"choices": [{"delta": {"content": '{"fact_ids":["plan"]}'}}]})
        return httpx.Response(200, text=f"data: {content}\n\ndata: [DONE]\n\n")
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(model)))
    signed.patch("/api/settings/llm", json={**CONNECTION, "api_key": "fixture-key"})
    response = signed.post("/api/coach", json={"fen": chess.STARTING_FEN, "question": "What should I focus on?"})
    assert "local_llm_verified" in response.text
    assert requests[0].url == "http://model-server:8000/v1/chat/completions"
    assert "fixture-key" not in response.text
    cleared = signed.patch("/api/settings/llm", json={"base_url": "", "model": ""})
    assert cleared.json() == {"base_url": "", "model": "", "has_api_key": False, "configured": False}
    response = signed.post("/api/coach", json={"fen": chess.STARTING_FEN, "question": "What should I focus on?"})
    assert "deterministic" in response.text and len(requests) == 1
