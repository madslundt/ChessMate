"""Session commands for installations which enable authenticated profiles."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .auth import _public
from .config import settings
from .database import get_db
from .models import AuthSession, User
from .profile_security import COOKIE, authenticate, digest, password_hash, password_matches, session_user, start_session, throttle

router = APIRouter(prefix="/profiles", tags=["Profiles"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    password: SecretStr = Field(min_length=1, max_length=256)


class PasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: SecretStr = Field(min_length=1, max_length=256)
    password: SecretStr = Field(min_length=12, max_length=256)


@router.get("/access")
def access(request: Request, db: Session = Depends(get_db)) -> dict:
    user = session_user(request, db) if settings.secure_deployment else None
    return {"secure_mode": settings.secure_deployment, "registration_allowed": settings.allow_registration,
            "authenticated": user is not None, "profile_id": user.id if user else None}


@router.post("/session")
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    if not settings.secure_deployment: raise HTTPException(404, "Authenticated mode is disabled")
    throttle(request, data.name.strip())
    user = db.scalar(select(User).where(func.lower(User.name) == data.name.strip().casefold()))
    if not password_matches(data.password.get_secret_value(), user.password_hash if user else ""):
        raise HTTPException(401, "Incorrect profile name or password")
    start_session(request, response, db, user)
    return _public(user)


@router.delete("/session", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == digest(token)))
        db.commit()
    response.delete_cookie(COOKIE, path="/", httponly=True, secure=settings.cookie_secure, samesite="strict")


@router.patch("/password", status_code=204)
def change_password(data: PasswordRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    if not settings.secure_deployment: raise HTTPException(404, "Authenticated mode is disabled")
    user = authenticate(request, db)
    throttle(request, user.name)
    if not password_matches(data.current_password.get_secret_value(), user.password_hash):
        raise HTTPException(401, "Incorrect current password")
    user.password_hash = password_hash(data.password.get_secret_value())
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.commit()
    start_session(request, response, db, user)
