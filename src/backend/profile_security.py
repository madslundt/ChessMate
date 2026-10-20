"""Optional password authentication; default trusted local profiles stay compatible."""
from collections import OrderedDict
from datetime import timedelta, timezone
import hashlib
import hmac
import secrets
import threading
import time

from fastapi import HTTPException, Request, Response
from sqlalchemy import delete
from sqlalchemy.orm import Session

from .config import settings
from .models import AuthSession, User, now

COOKIE = "chessmate_session"
ITERATIONS = 600_000
SESSION_DAYS = 7
_attempts: OrderedDict[str, list[float]] = OrderedDict()
_lock = threading.Lock()
_hash_slots = threading.BoundedSemaphore(4)


def password_hash(password: str, *, salt: str | None = None) -> str:
    if not 12 <= len(password) <= 256:
        raise HTTPException(422, "Use a password of 12–256 characters")
    salt = salt or secrets.token_hex(16)
    if not _hash_slots.acquire(blocking=False): raise HTTPException(503, "Sign-in is busy; retry shortly")
    try:
        derived = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
        return f"pbkdf2_sha256${ITERATIONS}${salt}${derived.hex()}"
    finally:
        _hash_slots.release()


def password_matches(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        valid = algorithm == "pbkdf2_sha256" and int(iterations) == ITERATIONS and len(salt) == 32 and len(expected) == 64
        if not valid: raise ValueError("Unknown password encoding")
        bytes.fromhex(salt)
    except (ValueError, TypeError):
        salt, expected = "00" * 16, "00" * 32
        valid = False
    # Do the same expensive work for unknown profiles and unsupported legacy hashes.
    candidate = password_hash(password if 12 <= len(password) <= 256 else "invalid-password-value", salt=salt)
    return hmac.compare_digest(candidate.rsplit("$", 1)[1], expected) and valid and 12 <= len(password) <= 256


def throttle(request: Request, name: str) -> None:
    stamp = time.monotonic()
    # Do not trust client-controlled forwarding headers for rate limits.
    address = request.client.host if request.client else "unknown"
    keys = ["address:" + address, "profile:" + name.casefold()]
    with _lock:
        for key in keys:
            recent = [value for value in _attempts.get(key, []) if stamp - value < 60]
            if len(recent) >= (20 if key.startswith("address:") else 8):
                raise HTTPException(429, "Too many sign-in attempts. Try again in a minute.", headers={"Retry-After": "60"})
        for key in keys:
            _attempts[key] = [value for value in _attempts.get(key, []) if stamp - value < 60] + [stamp]
            _attempts.move_to_end(key)
        while len(_attempts) > 10000: _attempts.popitem(last=False)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 256: return None
    session = db.get(AuthSession, digest(token))
    if session is None: return None
    expiry = session.expires_at
    if expiry.tzinfo is None: expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= now(): return None
    return db.get(User, session.user_id)


def authenticate(request: Request, db: Session) -> User:
    user = session_user(request, db)
    if user is None:
        raise HTTPException(401, {"code": "authentication_required", "message": "Sign in to continue"})
    return user


def start_session(request: Request, response: Response, db: Session, user: User) -> None:
    old = request.cookies.get(COOKIE)
    if old: db.execute(delete(AuthSession).where(AuthSession.token_hash == digest(old)))
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now()))
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=digest(token), user_id=user.id, expires_at=now() + timedelta(days=SESSION_DAYS)))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=settings.cookie_secure, samesite="strict", path="/")
