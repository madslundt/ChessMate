"""Per-profile OpenAI-compatible STT and TTS providers."""
import json
import ssl
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import Field, SecretStr, StrictBool, ValidationError, field_validator, model_validator
from sqlalchemy.orm import Session

from .auth import current_user
from .config import llm_tls_context
from .database import get_db
from .models import SpeechSettings, User
from .schemas import Input

router = APIRouter(tags=["Speech"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_SPEECH_BYTES = 20 * 1024 * 1024
ALLOWED_AUDIO_TYPES = {
    "audio/flac", "audio/mp4", "audio/m4a", "audio/mpeg", "audio/mp3",
    "audio/ogg", "audio/wav", "audio/webm", "audio/x-flac", "audio/x-m4a", "audio/x-wav",
}
ALLOWED_SPEECH_TYPES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg", "audio/flac", "audio/mp4", "application/octet-stream"}


class SpeechSettingsPatch(Input):
    stt_mode: str | None = None
    tts_mode: str | None = None
    stt_base_url: str | None = None
    stt_model: str | None = None
    tts_base_url: str | None = None
    tts_model: str | None = None
    tts_voice: str | None = None
    tts_format: str | None = None
    verify_tls: StrictBool | None = None
    stt_api_key: SecretStr | None = None
    tts_api_key: SecretStr | None = None
    clear_stt_api_key: bool = False
    clear_tts_api_key: bool = False

    @field_validator("stt_mode", "tts_mode")
    @classmethod
    def valid_mode(cls, value):
        if value not in ("browser", "server"):
            raise ValueError("Mode must be browser or server")
        return value

    @field_validator("stt_base_url", "tts_base_url")
    @classmethod
    def valid_url(cls, value):
        if value is None:
            return value
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

    @field_validator("stt_model", "tts_model", "tts_voice")
    @classmethod
    def valid_label(cls, value):
        if value is None:
            return value
        value = value.strip()
        if len(value) > 200 or any(ord(c) < 32 for c in value):
            raise ValueError("Value must be at most 200 characters without control characters")
        return value

    @field_validator("tts_format")
    @classmethod
    def valid_tts_format(cls, value):
        if value is not None and value not in ("mp3", "wav"):
            raise ValueError("TTS format must be mp3 or wav")
        return value

    @field_validator("stt_api_key", "tts_api_key")
    @classmethod
    def valid_key(cls, value):
        if value:
            raw = value.get_secret_value()
            if len(raw) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in raw):
                raise ValueError("API key must be at most 4096 printable ASCII characters")
        return value

    @model_validator(mode="after")
    def no_key_conflicts(self):
        if self.clear_stt_api_key and self.stt_api_key and self.stt_api_key.get_secret_value():
            raise ValueError("Choose either replacing or removing the STT API key")
        if self.clear_tts_api_key and self.tts_api_key and self.tts_api_key.get_secret_value():
            raise ValueError("Choose either replacing or removing the TTS API key")
        return self


class SpeechModelsInput(Input):
    provider: str
    base_url: str
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    verify_tls: StrictBool = True

    @field_validator("provider")
    @classmethod
    def valid_provider(cls, value):
        if value not in ("stt", "tts"):
            raise ValueError("Provider must be stt or tts")
        return value

    @field_validator("base_url")
    @classmethod
    def valid_base_url(cls, value):
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (not value or len(value) > 2000 or parsed.scheme not in ("http", "https") or not parsed.hostname
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
    def valid_models_key(cls, value):
        if value:
            raw = value.get_secret_value()
            if len(raw) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in raw):
                raise ValueError("API key must be at most 4096 printable ASCII characters")
        return value

    @model_validator(mode="after")
    def no_key_conflict(self):
        if self.clear_api_key and self.api_key and self.api_key.get_secret_value():
            raise ValueError("Choose either replacing or removing the API key")
        return self


class SynthesisInput(Input):
    text: str = Field(min_length=1, max_length=4000)
    language: str = Field(default="en", pattern="^(en|da)$")


def _row(db: Session, user: User) -> SpeechSettings:
    saved = db.get(SpeechSettings, user.id)
    if saved is None:
        saved = SpeechSettings(user_id=user.id)
        db.add(saved)
        db.flush()
    return saved


def _public(saved: SpeechSettings) -> dict:
    return {
        "stt_mode": saved.stt_mode,
        "tts_mode": saved.tts_mode,
        "stt_base_url": saved.stt_base_url,
        "stt_model": saved.stt_model,
        "tts_base_url": saved.tts_base_url,
        "tts_model": saved.tts_model,
        "tts_voice": saved.tts_voice,
        "tts_format": saved.tts_format,
        "verify_tls": saved.verify_tls,
        "has_stt_api_key": bool(saved.stt_api_key),
        "has_tts_api_key": bool(saved.tts_api_key),
    }


def _base(base_url: str) -> str:
    return base_url if base_url.endswith("/v1") else base_url + "/v1"


def _client(verify_tls: bool):
    return httpx.AsyncClient(timeout=45, verify=llm_tls_context() if verify_tls else False)


def _models_error(error: Exception) -> HTTPException:
    code, message = "invalid_response", "The endpoint did not return a valid model list."
    if isinstance(error, httpx.TimeoutException):
        code, message = "timeout", "The speech model server timed out."
    elif isinstance(error, httpx.ConnectError):
        cause, seen = error, set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, ssl.SSLCertVerificationError):
                code, message = "tls_certificate", "The backend does not trust the server certificate."
                break
            cause = cause.__cause__ or cause.__context__
        else:
            code, message = "connection", "The backend cannot connect to the speech model server."
    elif isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code in (401, 403):
            code, message = "authentication", "The speech model server rejected authentication."
        elif error.response.status_code == 404:
            code, message = "not_found", "The model-list API was not found."
        else:
            code, message = "server_error", "The speech model server returned an HTTP error."
    return HTTPException(502, {"code": code, "message": message})


@router.post("/settings/speech/models")
async def list_speech_models(data: dict, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try:
        draft = SpeechModelsInput.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_input=False, include_context=False)) from None
    saved = db.get(SpeechSettings, user.id)
    key_field = "stt_api_key" if draft.provider == "stt" else "tts_api_key"
    url_field = "stt_base_url" if draft.provider == "stt" else "tts_base_url"
    saved_key = getattr(saved, key_field, "") if saved else ""
    saved_url = getattr(saved, url_field, "") if saved else ""
    key = "" if draft.clear_api_key else (
        draft.api_key.get_secret_value() if draft.api_key else saved_key if draft.base_url == saved_url else ""
    )
    base_url = _base(draft.base_url)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=10, verify=llm_tls_context() if draft.verify_tls else False) as client:
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
            model = item["id"].strip()
            if not model or len(model) > 200 or any(ord(c) < 32 for c in model):
                raise ValueError("Invalid model identifier")
            models.add(model)
        return {"models": sorted(models)}
    except (httpx.HTTPError, ValueError) as error:
        raise _models_error(error) from None


def _provider_error(error: Exception) -> HTTPException:
    # Never return upstream response bodies, exception strings, or provider URLs.
    if isinstance(error, httpx.TimeoutException):
        return HTTPException(504, "The speech provider timed out")
    if isinstance(error, httpx.ConnectError):
        return HTTPException(502, "Could not connect to the speech provider")
    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code in (401, 403):
            return HTTPException(502, "The speech provider rejected authentication")
        return HTTPException(502, "The speech provider returned an error")
    return HTTPException(502, "The speech provider returned an invalid response")


@router.get("/settings/speech")
def get_speech_settings(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    saved = _row(db, user)
    db.commit()
    return _public(saved)


@router.patch("/settings/speech")
def patch_speech_settings(data: dict, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try:
        patch = SpeechSettingsPatch.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_input=False, include_context=False)) from None
    saved = _row(db, user)
    values = patch.model_dump(exclude_unset=True, exclude={"stt_api_key", "tts_api_key", "clear_stt_api_key", "clear_tts_api_key"})
    for name, value in values.items():
        if value is not None:
            setattr(saved, name, value)
    if patch.clear_stt_api_key:
        saved.stt_api_key = ""
    elif patch.stt_api_key and patch.stt_api_key.get_secret_value():
        saved.stt_api_key = patch.stt_api_key.get_secret_value()
    if patch.clear_tts_api_key:
        saved.tts_api_key = ""
    elif patch.tts_api_key and patch.tts_api_key.get_secret_value():
        saved.tts_api_key = patch.tts_api_key.get_secret_value()
    if saved.stt_mode == "server" and (not saved.stt_base_url or not saved.stt_model):
        raise HTTPException(422, "Configure an STT endpoint and model before selecting server mode")
    if saved.tts_mode == "server" and (not saved.tts_base_url or not saved.tts_model or not saved.tts_voice):
        raise HTTPException(422, "Configure a TTS endpoint, model, and voice before selecting server mode")
    db.commit()
    return _public(saved)


@router.post("/speech/transcribe")
async def transcribe(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    saved = db.get(SpeechSettings, user.id)
    if saved is None or saved.stt_mode != "server" or not saved.stt_base_url or not saved.stt_model:
        raise HTTPException(409, "Server transcription is not configured")
    media_type = (file.content_type or "").lower().split(";")[0].strip()
    if media_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(415, "Unsupported audio type")
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio must be between 1 byte and 10 MiB")
    filename = "recording" + (".webm" if media_type == "audio/webm" else ".wav" if "wav" in media_type else ".mp3" if media_type in ("audio/mpeg", "audio/mp3") else ".audio")
    headers = {"Authorization": f"Bearer {saved.stt_api_key}"} if saved.stt_api_key else {}
    try:
        async with _client(saved.verify_tls) as client:
            response = await client.post(
                _base(saved.stt_base_url) + "/audio/transcriptions",
                headers=headers,
                data={"model": saved.stt_model},
                files={"file": (filename, audio, media_type)},
            )
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                raise ValueError("response too large")
            payload = response.json()
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or len(text) > 20_000:
            raise ValueError("invalid transcription")
        return {"text": text}
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
        raise _provider_error(error) from None
    finally:
        await file.close()


@router.post("/speech/synthesize")
async def synthesize(data: SynthesisInput, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    saved = db.get(SpeechSettings, user.id)
    if saved is None or saved.tts_mode != "server" or not saved.tts_base_url or not saved.tts_model or not saved.tts_voice:
        raise HTTPException(409, "Server speech synthesis is not configured")
    headers = {"Authorization": f"Bearer {saved.tts_api_key}"} if saved.tts_api_key else {}
    payload = {"model": saved.tts_model, "input": data.text, "voice": saved.tts_voice, "response_format": saved.tts_format,
               "instructions": "Speak in English." if data.language == "en" else "Speak in Danish."}
    try:
        async with _client(saved.verify_tls) as client:
            async with client.stream("POST", _base(saved.tts_base_url) + "/audio/speech", headers=headers, json=payload) as response:
                response.raise_for_status()
                media_type = response.headers.get("content-type", "audio/mpeg").split(";")[0].lower().strip()
                if media_type not in ALLOWED_SPEECH_TYPES:
                    raise ValueError("unexpected media type")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_SPEECH_BYTES:
                        raise ValueError("speech response too large")
        if not body:
            raise ValueError("empty speech response")
        return Response(content=bytes(body), media_type=media_type, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    except (httpx.HTTPError, ValueError) as error:
        raise _provider_error(error) from None
