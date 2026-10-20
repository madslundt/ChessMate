"""Local account passwords and opaque, revocable, database-backed sessions."""
import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import AuthSession, User
from .schemas import Credentials, Preferences
from .views import UserView

router = APIRouter(prefix="/auth", tags=["Accounts"])
COOKIE = "chessmate_session"
_rate_lock = threading.Lock()
_attempts: dict[str, list[float]] = {}


def rate_limit(request: Request) -> None:
    host = request.client.host if request.client else "local"
    now = time.monotonic()
    with _rate_lock:
        for key in list(_attempts):
            _attempts[key] = [t for t in _attempts[key] if now - t < 300]
            if not _attempts[key]: del _attempts[key]
        attempts = _attempts.setdefault(host, [])
        if len(attempts) >= 20 or len(_attempts) > 10000:
            raise HTTPException(429, "Too many authentication attempts; try again in five minutes")
        attempts.append(now)


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def password_matches(password: str, encoded: str) -> bool:
    try:
        _, salt, _digest = encoded.split("$")
        return hmac.compare_digest(password_hash(password, salt), encoded)
    except ValueError:
        return False


def session_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE, "")
    session = db.get(AuthSession, session_hash(token)) if token else None
    if not session or session.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(401, "Sign in to continue")
    user = db.get(User, session.user_id)
    if not user: raise HTTPException(401, "Account no longer exists")
    return user


def public_user(user: User) -> dict:
    return {"id": user.id, "name": user.name,
            "preferences": Preferences.model_validate(user.preferences or {}).model_dump()}


def create_session(user: User, response: Response, db: Session) -> None:
    token = secrets.token_urlsafe(32)
    db.execute(delete(AuthSession).where(AuthSession.expires_at < datetime.now(timezone.utc)))
    db.add(AuthSession(token_hash=session_hash(token), user_id=user.id,
                       expires_at=datetime.now(timezone.utc) + timedelta(days=30)))
    db.commit()
    response.set_cookie(COOKIE, token, httponly=True, secure=settings.cookie_secure,
                        samesite="lax", max_age=30 * 86400, path="/")


@router.post("/register", status_code=201, response_model=UserView)
def register(data: Credentials, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    rate_limit(request)
    user = User(name=data.name.casefold(), password_hash=password_hash(data.password),
                preferences=Preferences().model_dump())
    db.add(user)
    try: db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That account name is already taken") from None
    create_session(user, response, db)
    return public_user(user)


@router.post("/login", response_model=UserView)
def login(data: Credentials, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    rate_limit(request)
    user = db.scalar(select(User).where(User.name == data.name.casefold()))
    # A dummy hash makes unknown-account authentication comparable in cost.
    valid = password_matches(data.password, user.password_hash if user else password_hash("invalid-password"))
    if not user or not valid: raise HTTPException(401, "Invalid account name or password")
    old = request.cookies.get(COOKIE)
    if old: db.execute(delete(AuthSession).where(AuthSession.token_hash == session_hash(old)))
    create_session(user, response, db)
    return public_user(user)


@router.get("/me", response_model=UserView)
def me(user: User = Depends(current_user)) -> dict:
    return public_user(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == session_hash(token)))
        db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}
