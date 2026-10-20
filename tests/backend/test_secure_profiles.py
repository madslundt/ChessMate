from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select

import src.backend.auth as auth
import src.backend.main as main
import src.backend.profile_security as security
import src.backend.secure_profiles as commands
from src.backend.models import AuthSession, User, now

PASSWORD = "correct horse battery test"


@pytest.fixture
def secure(client, monkeypatch):
    configured = replace(auth.settings, secure_deployment=True, allow_registration=True)
    for module in (auth, security, commands): monkeypatch.setattr(module, "settings", configured)
    security._attempts.clear()
    return client


def register(client, name="Learner", password=PASSWORD):
    response = client.post("/api/profiles", json={"name": name, "password": password})
    assert response.status_code == 201, response.text
    return response.json()


def test_secure_mode_requires_cookie_and_header_cannot_impersonate(secure):
    assert secure.get("/api/profiles").status_code == 401
    assert secure.get("/api/settings", headers={"X-Profile-ID": "guessed"}).status_code == 401
    first = register(secure)
    game = secure.post("/api/games", json={}).json()
    second = register(secure, "Other")
    assert [p["id"] for p in secure.get("/api/profiles").json()] == [second["id"]]
    assert secure.get("/api/settings", headers={"X-Profile-ID": first["id"]}).status_code == 403
    assert secure.get(f"/api/games/{game['id']}").status_code == 404
    assert secure.patch(f"/api/profiles/{first['id']}", json={"name": "stolen"}).status_code == 404
    assert secure.delete(f"/api/profiles/{first['id']}").status_code == 404
    assert PASSWORD not in secure.get("/api/profiles").text


def test_login_rotates_opaque_cookie_logout_revokes_and_hashes_are_not_exposed(secure):
    profile = register(secure)
    old = secure.cookies.get(security.COOKIE)
    response = secure.post("/api/profiles/session", json={"name": "learner", "password": PASSWORD})
    assert response.status_code == 200 and response.json()["id"] == profile["id"]
    token = secure.cookies.get(security.COOKIE)
    assert old != token and "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=strict" in response.headers["set-cookie"].lower()
    with main.SessionLocal() as db:
        user = db.get(User, profile["id"])
        assert user.password_hash != PASSWORD and user.password_hash.startswith("pbkdf2_sha256$600000$")
        sessions = db.scalars(select(AuthSession)).all()
        assert [s.token_hash for s in sessions] == [security.digest(token)]
        assert all(s.token_hash != token for s in sessions)
    assert secure.delete("/api/profiles/session").status_code == 204
    assert secure.get("/api/settings").status_code == 401
    secure.cookies.set(security.COOKIE, token)
    assert secure.get("/api/settings").status_code == 401


def test_missing_password_and_disabled_registration_are_explicit(secure, monkeypatch):
    assert secure.post("/api/profiles", json={"name": "new"}).status_code == 422
    assert secure.post("/api/profiles", json={"name": "new", "password": "short"}).status_code == 422
    monkeypatch.setattr(auth, "settings", replace(auth.settings, allow_registration=False))
    assert secure.post("/api/profiles", json={"name": "new", "password": PASSWORD}).status_code == 403


def test_expired_session_and_password_change_revoke_old_sessions(secure):
    profile = register(secure)
    token = secure.cookies.get(security.COOKIE)
    with main.SessionLocal() as db:
        session = db.get(AuthSession, security.digest(token))
        session.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert secure.get("/api/settings").status_code == 401
    assert secure.post("/api/profiles/session", json={"name": profile["name"], "password": PASSWORD}).status_code == 200
    before = secure.cookies.get(security.COOKIE)
    changed = "a different long password"
    assert secure.patch("/api/profiles/password", json={"current_password": PASSWORD, "password": changed}).status_code == 204
    assert secure.cookies.get(security.COOKIE) != before
    assert secure.post("/api/profiles/session", json={"name": profile["name"], "password": PASSWORD}).status_code == 401
    assert secure.post("/api/profiles/session", json={"name": profile["name"], "password": changed}).status_code == 200


def test_uniform_login_failure_and_rate_limit(secure):
    register(secure)
    security._attempts.clear()
    missing = secure.post("/api/profiles/session", json={"name": "Nobody", "password": PASSWORD})
    wrong = secure.post("/api/profiles/session", json={"name": "Learner", "password": "wrong-password-value"})
    assert missing.status_code == wrong.status_code == 401 and missing.json() == wrong.json()
    for _ in range(7):
        assert secure.post("/api/profiles/session", json={"name": "Learner", "password": "wrong-password-value"}).status_code == 401
    blocked = secure.post("/api/profiles/session", json={"name": "Learner", "password": "wrong-password-value"})
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"


def test_secure_registration_shares_bounded_attempt_limits(secure):
    register(secure)
    for _ in range(7):
        assert secure.post("/api/profiles", json={"name": "Learner", "password": PASSWORD}).status_code == 409
    assert secure.post("/api/profiles", json={"name": "Learner", "password": PASSWORD}).status_code == 429


def test_local_profiles_remain_passwordless_and_session_route_does_not_shadow_deletion(client):
    assert client.post("/api/profiles/session", json={"name": "x", "password": PASSWORD}).status_code == 404
    profile = client.post("/api/profiles", json={"name": "local"}).json()
    assert "authenticated" not in profile
    assert client.delete(f"/api/profiles/{profile['id']}").status_code == 204
