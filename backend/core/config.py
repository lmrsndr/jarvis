from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT_DIR / ".env"
ENV_PATHS = (ROOT_DIR.parent / ".env", ENV_PATH)


def _load_dotenv(paths: tuple[Path, ...] = ENV_PATHS) -> None:
    existing_paths = [path for path in paths if path.exists()]
    if not existing_paths:
        return

    for path in existing_paths:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _path_env(name: str, default: Path) -> str:
    value = os.getenv(name)
    if not value:
        return str(default)
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(ROOT_DIR / path)


def _list_env(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("JARVIS_HOST", "127.0.0.1")
    port: int = int(os.getenv("JARVIS_PORT", "8000"))
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.1")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    admin_password_hash: str = os.getenv("JARVIS_ADMIN_PASSWORD_HASH", "")
    local_only: bool = _bool_env("JARVIS_LOCAL_ONLY", True)
    allow_remote: bool = _bool_env("JARVIS_ALLOW_REMOTE", False)
    allowed_origins: list[str] = None
    memory_db_path: str = _path_env("JARVIS_MEMORY_DB_PATH", ROOT_DIR / "storage" / "jarvis.db")
    vector_path: str = _path_env("JARVIS_VECTOR_PATH", ROOT_DIR / "storage" / "memory_files" / "vectors.json")
    stt_provider: str = os.getenv("JARVIS_STT_PROVIDER", "local")
    stt_model: str = os.getenv("JARVIS_STT_MODEL", "base")

    def __post_init__(self) -> None:
        if self.allowed_origins is None:
            object.__setattr__(
                self,
                "allowed_origins",
                ["http://127.0.0.1:5173", "http://localhost:5173"],
            )

    @property
    def default_provider(self) -> str:
        return "ollama"

    def provider_available(self, name: str) -> bool:
        if name == "ollama":
            return True
        if name == "openai":
            return bool(self.openai_api_key)
        if name == "gemini":
            return bool(self.gemini_api_key)
        return False


def get_settings() -> Settings:
    _load_dotenv()
    return Settings(
        host=os.getenv("JARVIS_HOST", "127.0.0.1"),
        port=int(os.getenv("JARVIS_PORT", "8000")),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
        admin_password_hash=os.getenv("JARVIS_ADMIN_PASSWORD_HASH", ""),
        local_only=_bool_env("JARVIS_LOCAL_ONLY", True),
        allow_remote=_bool_env("JARVIS_ALLOW_REMOTE", False),
        allowed_origins=_list_env(
            "JARVIS_ALLOWED_ORIGINS",
            ["http://127.0.0.1:5173", "http://localhost:5173"],
        ),
        memory_db_path=_path_env("JARVIS_MEMORY_DB_PATH", ROOT_DIR / "storage" / "jarvis.db"),
        vector_path=_path_env("JARVIS_VECTOR_PATH", ROOT_DIR / "storage" / "memory_files" / "vectors.json"),
        stt_provider=os.getenv("JARVIS_STT_PROVIDER", "local"),
        stt_model=os.getenv("JARVIS_STT_MODEL", "base"),
    )
