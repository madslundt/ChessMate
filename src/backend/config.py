"""Server-owned configuration; credentials never appear in API responses."""
import os
import ssl
from dataclasses import dataclass, field


def number(name: str, default: float, low: float, high: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./config/chessmate.db"))
    stockfish_path: str = field(default_factory=lambda: os.getenv("STOCKFISH_PATH", ""))
    engine_threads: int = field(default_factory=lambda: int(number("ENGINE_THREADS", 1, 1, 8)))
    engine_hash_mb: int = field(default_factory=lambda: int(number("ENGINE_HASH_MB", 64, 16, 512)))
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "").rstrip("/"))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    llm_ca_bundle: str = field(default_factory=lambda: os.getenv("LLM_CA_BUNDLE", ""))
    llm_timeout: float = field(default_factory=lambda: number("LLM_TIMEOUT", 35, 1, 180))
    llm_max_tokens: int = field(default_factory=lambda: int(number("LLM_MAX_TOKENS", 600, 100, 2000)))
    llm_temperature: float = field(default_factory=lambda: number("LLM_TEMPERATURE", 0.2, 0, 2))
    llm_reasoning_effort: str = field(default_factory=lambda: os.getenv("LLM_REASONING_EFFORT", "").strip())
    cookie_secure: bool = field(default_factory=lambda: os.getenv("COOKIE_SECURE", "false").lower() == "true")
    secure_deployment: bool = field(default_factory=lambda: os.getenv("SECURE_DEPLOYMENT", "false").lower() == "true")
    allow_registration: bool = field(default_factory=lambda: os.getenv("ALLOW_REGISTRATION", "false").lower() == "true")
    allowed_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        value.strip() for value in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080").split(",") if value.strip()))


settings = Settings()


def llm_tls_context() -> ssl.SSLContext:
    """Keep public roots and hostname checks; optionally trust a local inference CA."""
    context = ssl.create_default_context()
    if settings.llm_ca_bundle:
        context.load_verify_locations(cafile=settings.llm_ca_bundle)
    return context
