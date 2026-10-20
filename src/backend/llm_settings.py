"""Account-owned inference connections. Credentials never enter coaching context or responses."""
from dataclasses import dataclass, field
import json
import ssl
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import SecretStr, StrictBool, ValidationError, field_validator, model_validator
from sqlalchemy.orm import Session

from .auth import current_user
from .config import settings, llm_tls_context
from .database import get_db
from .models import LlmConnection, User
from .schemas import Input

router = APIRouter(prefix="/settings/llm", tags=["Settings"])


@dataclass(frozen=True)
class Connection:
    base_url: str
    model: str
    api_key: str = field(default="", repr=False)
    verify_tls: bool = True


class EndpointInput(Input):
    base_url: str
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    verify_tls: StrictBool | None = None

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
        return Connection(saved.base_url, saved.model, saved.api_key, saved.verify_tls)
    return Connection(settings.llm_base_url, settings.llm_model, settings.llm_api_key)


def public_connection(connection: Connection) -> dict:
    return {"base_url": connection.base_url, "model": connection.model,
            "has_api_key": bool(connection.api_key), "configured": bool(connection.base_url and connection.model),
            "verify_tls": connection.verify_tls}


def connection_key(draft: EndpointInput, previous: Connection) -> str:
    if not draft.base_url or draft.clear_api_key:
        return ""
    key = draft.api_key.get_secret_value() if draft.api_key else ""
    if not key and draft.base_url == previous.base_url:
        key = previous.api_key
    return key


def connection_verifies_tls(draft: EndpointInput, previous: Connection) -> bool:
    if draft.verify_tls is not None:
        return draft.verify_tls
    return previous.verify_tls if draft.base_url == previous.base_url else True


@router.post("/models")
async def list_models(data: dict, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try:
        draft = EndpointInput.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_input=False, include_context=False)) from None
    if not draft.base_url:
        raise HTTPException(422, "Provide an endpoint to load models")
    previous = connection_for(db, user)
    key = connection_key(draft, previous)
    verify_tls = connection_verifies_tls(draft, previous)
    base_url = draft.base_url if draft.base_url.endswith("/v1") else draft.base_url + "/v1"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=10, verify=llm_tls_context() if verify_tls else False) as client:
            async with client.stream("GET", base_url + "/models", headers=headers) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000:
                        raise ValueError("Model catalog is too large")
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
    except (httpx.HTTPError, ValueError) as error:
        # Provider errors may contain credentials or private URLs; never relay their bodies.
        code, message = "invalid_response", "The endpoint did not return a valid model list. Choose Custom to enter a model name."
        if isinstance(error, httpx.TimeoutException):
            code, message = "timeout", "The model server timed out. Check the endpoint address and port, or choose Custom."
        elif isinstance(error, httpx.ConnectError):
            cause, seen = error, set()
            while cause is not None and id(cause) not in seen:
                seen.add(id(cause))
                if isinstance(cause, ssl.SSLCertVerificationError):
                    code, message = "tls_certificate", "The backend does not trust the server certificate. Configure its local CA certificate, or choose Custom."
                    break
                cause = cause.__cause__ or cause.__context__
            else:
                code, message = "connection", "The backend cannot connect to the model server. Check its hostname and port, or choose Custom."
        elif isinstance(error, httpx.HTTPStatusError):
            if error.response.status_code in (401, 403):
                code, message = "authentication", "The model server rejected authentication. Check the API key, or choose Custom."
            elif error.response.status_code == 404:
                code, message = "not_found", "The model-list API was not found. Check the API base URL, or choose Custom."
            else:
                code, message = "server_error", "The model server returned an HTTP error. Try again or choose Custom."
        raise HTTPException(502, {"code": code, "message": message}) from None


@router.post("/test")
async def test_connection(data: dict, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try:
        draft = ConnectionInput.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_input=False, include_context=False)) from None
    if not draft.base_url or not draft.model:
        raise HTTPException(409, "Configure an endpoint and model before testing")
    previous = connection_for(db, user)
    key = connection_key(draft, previous)
    verify_tls = connection_verifies_tls(draft, previous)
    base_url = draft.base_url if draft.base_url.endswith("/v1") else draft.base_url + "/v1"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    payload = {
        "model": draft.model,
        "messages": [{"role": "user", "content": "Reply with the single word OK."}],
        "max_tokens": 16,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=20, verify=llm_tls_context() if verify_tls else False) as client:
            response = await client.post(base_url + "/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
        if len(response.content) > 1_000_000:
            raise ValueError("response too large")
        result = response.json()
        choices = result.get("choices") if isinstance(result, dict) else None
        message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
        reply = message.get("content") if isinstance(message, dict) else None
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("invalid completion response")
        return {"reply": reply.strip()[:1000]}
    except httpx.TimeoutException:
        raise HTTPException(504, "The model server timed out") from None
    except httpx.ConnectError as error:
        cause, seen = error, set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, ssl.SSLCertVerificationError):
                raise HTTPException(502, "The backend does not trust the model server certificate") from None
            cause = cause.__cause__ or cause.__context__
        raise HTTPException(502, "Could not connect to the model server") from None
    except httpx.HTTPStatusError as error:
        if error.response.status_code in (401, 403):
            message = "The model server rejected authentication"
        else:
            message = "The model server returned an error"
        raise HTTPException(502, message) from None
    except (httpx.HTTPError, ValueError, json.JSONDecodeError):
        raise HTTPException(502, "The model server returned an invalid response") from None


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
    saved.verify_tls = connection_verifies_tls(draft, previous)
    db.commit()
    return public_connection(Connection(saved.base_url, saved.model, saved.api_key, saved.verify_tls))
