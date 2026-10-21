import json

import chess
import httpx
import pytest


def test_private_ca_is_required_and_hostname_verification_remains_enabled(monkeypatch, tmp_path):
    import asyncio
    import shutil
    import ssl
    import subprocess
    import threading
    from dataclasses import replace
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import src.backend.config as config
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from src.backend.database import Base
    from src.backend.models import User
    from src.backend.llm_settings import Connection, connection_for, list_models, save_connection
    from src.backend.coach import CoachService

    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("TLS integration fixture requires openssl")
    certificate, key = tmp_path / "test-ca.pem", tmp_path / "test.key"
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
                    "-keyout", str(key), "-out", str(certificate)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_GET(self):
            body = b'{"data":[{"id":"private-tls-model"}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            chunk = json.dumps({"choices": [{"delta": {"content": '{"fact_ids":["plan"]}'}}]})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(f"data: {chunk}\n\ndata: [DONE]\n\n".encode())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(id="tls-regression", name="TLS fixture", password_hash="")
    db.add(user)
    db.commit()
    monkeypatch.setattr(config, "settings", replace(config.settings, llm_ca_bundle=""))
    def discover(endpoint, **options):
        return asyncio.run(list_models({"base_url": endpoint, **options}, user, db))
    try:
        endpoint = f"https://localhost:{server.server_port}/v1"
        with pytest.raises(HTTPException) as initial:
            discover(endpoint)
        assert initial.value.status_code == 502
        assert initial.value.detail["code"] == "tls_certificate"
        assert discover(endpoint, verify_tls=False) == {"models": ["private-tls-model"]}
        service = CoachService()
        unverified = Connection(endpoint, "tls-fixture", verify_tls=False)
        selection = asyncio.run(service._model_selection({}, {"plan": "Verified fact"}, unverified))
        assert selection.fact_ids == ["plan"]
        saved = save_connection({"base_url": endpoint, "model": "tls-fixture", "verify_tls": False}, user, db)
        assert saved["verify_tls"] is False and connection_for(db, user).verify_tls is False
        assert discover(endpoint) == {"models": ["private-tls-model"]}
        assert connection_for(db, User(id="other-profile")).verify_tls is True
        with pytest.raises(HTTPException):
            discover(endpoint.replace("localhost", "127.0.0.1"))
        with pytest.raises(HTTPException):
            discover(endpoint, verify_tls=True)
        save_connection({"base_url": endpoint, "model": "tls-fixture", "verify_tls": True}, user, db)
        monkeypatch.setattr(config, "settings", replace(config.settings, llm_ca_bundle=str(certificate)))
        assert discover(endpoint) == {"models": ["private-tls-model"]}
        selection = asyncio.run(service._model_selection({}, {"plan": "Verified fact"}, connection_for(db, user)))
        assert selection.fact_ids == ["plan"]
        with pytest.raises(HTTPException) as wrong_host:
            discover(endpoint.replace("localhost", "127.0.0.1"))
        assert wrong_host.value.status_code == 502 and wrong_host.value.detail["code"] == "tls_certificate"
        save_connection({"base_url": endpoint, "model": "tls-fixture", "verify_tls": False}, user, db)
        changed = save_connection({"base_url": "https://another-server/v1", "model": "tls-fixture"}, user, db)
        assert changed["verify_tls"] is True
    finally:
        db.close()
        engine.dispose()
        server.shutdown()
        server.server_close()
        thread.join()


CONNECTION = {"base_url": "http://model-server:8000/v1", "model": "local-chess-model"}


@pytest.mark.parametrize("completion", [
    "OK",
    "",
    '{"fact_ids":["invented_fact"]}',
    '{"response":"Your queen wins by force.","fact_ids":["plan"]}',
])
def test_settings_probe_rejects_responses_that_cannot_produce_verified_coaching(signed, monkeypatch, completion):
    def provider(request):
        payload = json.loads(request.content)
        if not payload.get("stream"):
            # The old connectivity-only probe reports success for this same server.
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        event = {"choices": [{"delta": {"content": completion}, "finish_reason": "stop"}]}
        return httpx.Response(200, text=f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n")
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(provider)))
    before = signed.get("/api/settings/llm").json()
    response = signed.post("/api/settings/llm/test", json=CONNECTION)
    assert response.status_code == 502, response.text
    assert "verified coaching" in response.json()["detail"]
    assert signed.get("/api/settings/llm").json() == before


def test_settings_probe_uses_coaching_protocol_and_unsaved_connection(signed, monkeypatch):
    requests = []
    def provider(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.headers["Authorization"] == "Bearer draft-secret"
        if not payload.get("stream"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        content = '{"segments":[{"fact_id":"plan","framing":"consider"}]}'
        event = {"choices": [{"delta": {"content": content}}]}
        return httpx.Response(200, text=f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n")
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(provider)))
    before = signed.get("/api/settings/llm").json()
    response = signed.post("/api/settings/llm/test", json={**CONNECTION, "api_key": "draft-secret"})
    assert response.status_code == 200, response.text
    assert requests[0]["stream"] is True
    assert "statement_catalog" in requests[0]["messages"][1]["content"]
    assert "center" in response.json()["reply"]
    assert "draft-secret" not in response.text
    assert signed.get("/api/settings/llm").json() == before


@pytest.mark.parametrize("budget,effort,status", [(600, "", 502), (2000, "", 200), (600, "none", 200)])
def test_settings_probe_detects_reasoning_budget_exhaustion(signed, monkeypatch, budget, effort, status):
    from dataclasses import replace
    import src.backend.coach as coach
    monkeypatch.setattr(coach, "settings", replace(coach.settings, llm_max_tokens=budget, llm_reasoning_effort=effort))
    def provider(request):
        payload = json.loads(request.content)
        assert payload["max_tokens"] == coach.settings.llm_max_tokens
        if not payload.get("stream"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        if payload.get("reasoning_effort") == "none" or payload["max_tokens"] >= 2000:
            delta, finish = {"reasoning_content": "Choosing relevant evidence...", "content": '{"fact_ids":["plan"]}'}, "stop"
        else:
            # The actual automation-moe failure: HTTP 200, reasoning only, no final answer.
            delta, finish = {"reasoning_content": "Choosing relevant evidence...", "content": ""}, "length"
        event = {"choices": [{"delta": delta, "finish_reason": finish}]}
        return httpx.Response(200, text=f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n")
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(provider)))
    response = signed.post("/api/settings/llm/test", json=CONNECTION)
    assert response.status_code == status, response.text


def test_connection_requires_selected_profile(client):
    assert client.get("/api/settings/llm").status_code == 400
    assert client.patch("/api/settings/llm", json=CONNECTION).status_code == 400
    assert client.post("/api/settings/llm/models", json={"base_url": CONNECTION["base_url"]}).status_code == 400


def test_save_preserve_remove_key_and_persist(signed):
    secret = "test-only-provider-secret"
    response = signed.patch("/api/settings/llm", json={**CONNECTION, "api_key": secret})
    assert response.status_code == 200
    assert response.json() == {**CONNECTION, "has_api_key": True, "configured": True, "verify_tls": True}
    assert secret not in response.text
    assert secret not in signed.get("/api/settings/llm").text
    assert secret not in signed.get("/api/profiles").text
    assert secret not in signed.get("/api/settings").text
    profile_id = signed.headers.pop("X-Profile-ID")
    assert signed.get("/api/settings/llm").status_code == 400
    signed.headers["X-Profile-ID"] = profile_id
    assert signed.get("/api/settings/llm").json()["model"] == CONNECTION["model"]
    response = signed.patch("/api/settings/llm", json={**CONNECTION, "model": "another-model"})
    assert response.json()["has_api_key"] is True
    assert signed.patch("/api/settings/llm", json={**CONNECTION, "clear_api_key": True}).json()["has_api_key"] is False


def test_endpoint_change_cannot_forward_old_key_and_profiles_are_isolated(signed):
    signed.patch("/api/settings/llm", json={**CONNECTION, "api_key": "old-key"})
    changed = {**CONNECTION, "base_url": "http://different-server:8000/v1"}
    assert signed.patch("/api/settings/llm", json=changed).json()["has_api_key"] is False
    other = signed.post("/api/profiles", json={"name": "separate-profile"})
    assert other.status_code == 201
    signed.headers["X-Profile-ID"] = other.json()["id"]
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
    assert cleared.json() == {"base_url": "", "model": "", "has_api_key": False, "configured": False, "verify_tls": True}
    response = signed.post("/api/coach", json={"fen": chess.STARTING_FEN, "question": "What should I focus on?"})
    assert "deterministic" in response.text and len(requests) == 1


@pytest.mark.parametrize("base_url", ["http://model-server:8000", "http://model-server:8000/v1/"])
def test_discovers_all_models_from_unsaved_endpoint_without_key(signed, monkeypatch, base_url):
    identifiers = [f"model-{i:03}" for i in range(120)]
    def handler(request):
        assert request.method == "GET" and str(request.url) == "http://model-server:8000/v1/models"
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"data": [{"id": model} for model in [*reversed(identifiers), identifiers[0]]]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))
    before = signed.get("/api/settings/llm").json()
    response = signed.post("/api/settings/llm/models", json={"base_url": base_url})
    assert response.status_code == 200 and response.json() == {"models": identifiers}
    assert signed.get("/api/settings/llm").json() == before


def test_discovery_uses_draft_or_saved_key_only_for_the_same_endpoint(signed, monkeypatch):
    authorizations = []
    def handler(request):
        authorizations.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"data": [{"id": "available-model"}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))
    signed.patch("/api/settings/llm", json={**CONNECTION, "api_key": "saved-private-key"})
    for body in [
        {"base_url": CONNECTION["base_url"]},
        {"base_url": "http://other-server:8000/v1"},
        {"base_url": CONNECTION["base_url"], "api_key": "draft-private-key"},
        {"base_url": CONNECTION["base_url"], "clear_api_key": True},
    ]:
        response = signed.post("/api/settings/llm/models", json=body)
        assert response.status_code == 200 and "private-key" not in response.text
    assert authorizations == ["Bearer saved-private-key", None, "Bearer draft-private-key", None]
    assert signed.get("/api/settings/llm").json()["has_api_key"] is True


@pytest.mark.parametrize("failure", ["unauthorized", "unsupported", "timeout", "malformed", "invalid_ids", "oversized"])
def test_discovery_failure_is_safe_and_does_not_change_connection(signed, monkeypatch, failure):
    def handler(request):
        if failure == "timeout": raise httpx.ReadTimeout("private-key")
        if failure == "unauthorized": return httpx.Response(401, text="private-key")
        if failure == "unsupported": return httpx.Response(404, text="private-key")
        if failure == "malformed": return httpx.Response(200, text="private-key")
        if failure == "invalid_ids": return httpx.Response(200, json={"data": [{"id": 3}]})
        return httpx.Response(200, content=b"x" * 2_000_001)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))
    response = signed.post("/api/settings/llm/models", json={"base_url": CONNECTION["base_url"]})
    assert response.status_code == 502 and "Custom" in response.text
    assert "private-key" not in response.text


def test_discovery_validates_endpoint_before_network_request(signed):
    for base_url in ["", "file:///etc/passwd", "http://user:private-key@server/v1"]:
        response = signed.post("/api/settings/llm/models", json={"base_url": base_url})
        assert response.status_code == 422 and "private-key" not in response.text
