"""Trusted local profiles, with optional authenticated ownership."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuthSession, CoachingMessage, Game, GameEvent, HintUsage, LlmConnection, User
from .schemas import Preferences
from .training_models import Exercise, ExerciseAttempt, HintEvent, LearningProgress, OpeningLine, TrainingSession
from .views import UserView
from .config import settings
from .profile_security import authenticate, password_hash, start_session, throttle
from .coaching_models import CoachingEvidence, CoachingState
from .learning_models import LearningEvent

router = APIRouter(prefix="/profiles", tags=["Profiles"])


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    password: SecretStr | None = Field(default=None, min_length=12, max_length=256)


def current_user(request: Request, profile_id: str | None = Header(default=None, alias="X-Profile-ID"),
                 db: Session = Depends(get_db)) -> User:
    if settings.secure_deployment:
        user = authenticate(request, db)
        if profile_id and profile_id != user.id: raise HTTPException(403, "This session cannot select another profile")
        return user
    if not profile_id:
        raise HTTPException(400, "Select a profile to continue")
    user = db.get(User, profile_id)
    if not user:
        raise HTTPException(404, "Profile not found")
    return user


def _name(value: str) -> str:
    name = value.strip()
    if not name:
        raise HTTPException(422, "Profile name cannot be blank")
    return name


def _ensure_unique(db: Session, name: str, excluding: str | None = None) -> None:
    query = select(User.id).where(func.lower(User.name) == name.casefold())
    if excluding:
        query = query.where(User.id != excluding)
    if db.scalar(query):
        raise HTTPException(409, "A profile with that name already exists")


def _public(user: User) -> dict:
    return {"id": user.id, "name": user.name,
            "preferences": Preferences.model_validate(user.preferences or {}).model_dump(),
            **({"authenticated": True} if settings.secure_deployment else {})}


@router.get("", response_model=list[UserView])
def list_profiles(request: Request, db: Session = Depends(get_db)) -> list[dict]:
    if settings.secure_deployment: return [_public(authenticate(request, db))]
    return [_public(user) for user in db.scalars(select(User).order_by(User.created_at, User.name))]


@router.post("", status_code=201, response_model=UserView)
def create_profile(data: ProfileInput, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    if settings.secure_deployment and not settings.allow_registration:
        raise HTTPException(403, "Registration is disabled; ask the installation owner to create your account")
    if settings.secure_deployment and data.password is None:
        raise HTTPException(422, "A password is required in authenticated mode")
    name = _name(data.name)
    if settings.secure_deployment: throttle(request, name)
    _ensure_unique(db, name)
    user = User(name=name, password_hash=password_hash(data.password.get_secret_value()) if data.password else "", preferences=Preferences().model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    if settings.secure_deployment: start_session(request, response, db, user)
    return _public(user)


@router.patch("/{profile_id}", response_model=UserView)
def update_profile(profile_id: str, data: ProfileInput, request: Request, db: Session = Depends(get_db)) -> dict:
    if settings.secure_deployment and authenticate(request, db).id != profile_id:
        raise HTTPException(404, "Profile not found")
    if data.password is not None: raise HTTPException(422, "Use the password-change command")
    user = db.get(User, profile_id)
    if not user:
        raise HTTPException(404, "Profile not found")
    name = _name(data.name)
    _ensure_unique(db, name, excluding=profile_id)
    user.name = name
    db.commit()
    return _public(user)


@router.delete("/{profile_id}", status_code=204)
def delete_profile(profile_id: str, request: Request, db: Session = Depends(get_db)) -> None:
    if settings.secure_deployment and authenticate(request, db).id != profile_id:
        raise HTTPException(404, "Profile not found")
    user = db.get(User, profile_id)
    if not user:
        raise HTTPException(404, "Profile not found")
    game_ids = select(Game.id).where(Game.user_id == profile_id)
    # Remove owned data explicitly so deletion works with SQLite and PostgreSQL alike.
    message_ids = select(CoachingMessage.id).where(CoachingMessage.user_id == profile_id)
    db.execute(delete(CoachingEvidence).where(CoachingEvidence.message_id.in_(message_ids)))
    db.execute(delete(CoachingState).where(CoachingState.user_id == profile_id))
    db.execute(delete(LearningEvent).where(LearningEvent.user_id == profile_id))
    db.execute(delete(GameEvent).where(GameEvent.game_id.in_(game_ids)))
    db.execute(delete(CoachingMessage).where(CoachingMessage.user_id == profile_id))
    db.execute(delete(HintUsage).where(HintUsage.user_id == profile_id))
    db.execute(delete(ExerciseAttempt).where(ExerciseAttempt.user_id == profile_id))
    db.execute(delete(HintEvent).where(HintEvent.user_id == profile_id))
    db.execute(delete(LearningProgress).where(LearningProgress.user_id == profile_id))
    db.execute(delete(TrainingSession).where(TrainingSession.user_id == profile_id))
    db.execute(delete(OpeningLine).where(OpeningLine.user_id == profile_id))
    db.execute(delete(Exercise).where(Exercise.owner_id == profile_id))
    db.execute(delete(LlmConnection).where(LlmConnection.user_id == profile_id))
    db.execute(delete(AuthSession).where(AuthSession.user_id == profile_id))
    db.execute(delete(Game).where(Game.user_id == profile_id))
    db.delete(user)
    db.commit()
