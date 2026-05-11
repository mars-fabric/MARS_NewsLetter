"""Application settings — loaded from environment variables with sensible defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


def _csv(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


# Anchor for relative work-dir paths. Mirrors ``run.py``'s convention so a
# value like ``./cmbdir_newsletter`` always lands at
# ``MARS-NewsLetter/backend/cmbdir_newsletter`` regardless of the shell's cwd.
_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _resolve_work_dir(raw: str) -> str:
    expanded = os.path.expanduser(raw or "./cmbdir_newsletter")
    p = Path(expanded)
    if not p.is_absolute():
        p = _BACKEND_DIR / p
    return str(p.resolve())


@dataclass
class Settings:
    app_title: str = field(default_factory=lambda: os.getenv("NEWSLETTER_APP_TITLE", "MARS-NewsLetter API"))
    app_version: str = field(default_factory=lambda: os.getenv("NEWSLETTER_APP_VERSION", "0.1.0"))
    debug: bool = field(default_factory=lambda: os.getenv("NEWSLETTER_DEBUG", "false").lower() == "true")

    cors_origins: List[str] = field(default_factory=lambda: _csv(
        "NEWSLETTER_CORS_ORIGINS",
        [
            "http://localhost:3000", "http://127.0.0.1:3000",
            "http://localhost:3001", "http://127.0.0.1:3001",
        ],
    ))

    default_work_dir: str = field(default_factory=lambda: _resolve_work_dir(
        os.getenv("NEWSLETTER_DEFAULT_WORK_DIR")
        or os.getenv("CMBAGENT_DEFAULT_WORK_DIR")
        or "./cmbdir_newsletter"
    ))
    max_file_size_mb: int = field(default_factory=lambda: int(os.getenv("NEWSLETTER_MAX_FILE_SIZE_MB", "10")))

    # LLM provider creds — read once at startup; cmbagent's ProviderRegistry consumes them
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    google_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))

    azure_openai_api_key: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_API_KEY", ""))
    azure_openai_endpoint: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT", ""))
    azure_openai_deployment: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT", ""))
    azure_openai_api_version: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"))

    aws_access_key_id: str = field(default_factory=lambda: os.getenv("AWS_ACCESS_KEY_ID", ""))
    aws_secret_access_key: str = field(default_factory=lambda: os.getenv("AWS_SECRET_ACCESS_KEY", ""))
    aws_region: str = field(default_factory=lambda: os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION") or "")

    @property
    def expanded_work_dir(self) -> str:
        # Already resolved at dataclass init; kept for backwards-compat.
        return self.default_work_dir


settings = Settings()
