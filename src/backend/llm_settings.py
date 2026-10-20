"""Account-owned inference connections. Credentials never enter coaching context or responses."""
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import SecretStr, ValidationError, field_validator, model_validator
from sqlalchemy.orm import Session

from .auth import current_user
from .config import settings
from .database import get_db
from .models import LlmConnection, User
from .schemas import Input

router = APIRouter(prefix="/settings/llm", tags=["Settings"])


@dataclass(frozen=True)
class Connection:
    base_url: str
    model: str
    api_key: str = field(default="", repr=False)


class EndpointInput(Input):
    base_url: str
    api_key: SecretStr | None = None
    clear_api_key: bool = False

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return value
        parsed = urlsplit(value)
        if (len(value) > 2000 or parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
                or any(c.isspace() for c in value)):
            raise ValueError("Use an HTTP(S) API base URL without credentials, query parameters, or fragments")
        try:
            parsed.port
        except ValueError:
            raise ValueError("Invalid endpoint port") from None
        return value

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            raw = value.get_secret_value()
            if len(raw) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in raw):
                raise ValueError("API key must be at most 4096 printable ASCII characters")
        return value

    @model_validator(mode="after")
    def valid_credentials(self):
        if self.clear_api_key and self.api_key and self.api_key.get_secret_value():
            raise ValueError("Choose either replacing or removing the API key")
        return self


class ConnectionInput(EndpointInput):
    model: str

    @field_validator("model")
    @classmethod
    def valid_model(cls, value: str) -> str:
        value = value.strip()
        if len(value) > 200 or any(ord(c) < 32 for c in value):
            raise ValueError("Model must be at most 200 characters without control characters")
        return value

    @model_validator(mode="after")
    def complete_connection(self):
        if bool(self.base_url) != bool(self.model):
            raise ValueError("Provide both endpoint and model, or leave both empty to disable the LLM")
        return self


def connection_for(db: Session, user: User) -> Connection:
    saved = db.get(LlmConnection, user.id)
    if saved is not None:
        return Connection(saved.base_url, saved.model, saved.api_key)
    return Connection(settings.llm_base_url, settings.llm_model, settings.llm_api_key)


def public_connection(connection: Connection) -> dict:
    return {"base_url": connection.base_url, "model": connection.model,
            "has_api_key": bool(connection.api_key), "configured": bool(connection.base_url and connection.model)}


def connection_key(draft: EndpointInput, previous: Connection) -> str:
    if not draft.base_url or draft.clear_api_key:
        return ""
    key = draft.api_key.get_secret_value() if draft.api_key else ""
    if not key and draft.base_url == previous.base_url:
        key = previous.api_key
    return key


@router.post("/models")
async def list_models(data: dict, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try:
        draft = EndpointInput.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_input=False, include_context=False)) from None
    if not draft.base_url:
        raise HTTPException(422, "Provide an endpoint to load models")
    key = connection_key(draft, connection_for(db, user))
    base_url = draft.base_url if draft.base_url.endswith("/v1") else draft.base_url + "/v1"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            async with client.stream("GET", base_url + "/models", headers=headers) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000:
                        raise ValueError("Model catalog is too large")
                import json
                payload = json.loads(content)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("Invalid model catalog")
        models = set()
        for item in payload["data"]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ValueError("Invalid model identifier")
            model = ConnectionInput.valid_model(item["id"])
            if not model:
                raise ValueError("Empty model identifier")
            models.add(model)
        return {"models": sorted(models)}
    except (httpx.HTTPError, ValueError):
        # Provider errors may contain credentials or private URLs; never relay their bodies.
        raise HTTPException(502, "Could not load models. Check the endpoint and API key, or choose Custom.") from None


@router.get("")
def get_connection(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return public_connection(connection_for(db, user))


@router.patch("")
def save_connection(data: dict, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try:
        draft = ConnectionInput.model_validate(data)
    except ValidationError as exc:
        # Validation errors must not echo a submitted secret, even for invalid input.
        raise HTTPException(422, exc.errors(include_input=False, include_context=False)) from None
    previous = connection_for(db, user)
    key = connection_key(draft, previous)
    saved = db.get(LlmConnection, user.id)
    if saved is None:
        saved = LlmConnection(user_id=user.id)
        db.add(saved)
    saved.base_url, saved.model, saved.api_key = draft.base_url, draft.model, key
    db.commit()
    return public_connection(Connection(saved.base_url, saved.model, saved.api_key))
