#!/usr/bin/env python3
"""Run the MARS-NewsLetter backend server.

Loads environment variables from `.env.local` (if present) then `.env`, ensures
the work directory exists, and starts uvicorn with port/host taken from the
environment.

Layered env loading order — first hit wins, so `.env.local` overrides `.env`:

    1. <repo>/.env.local
    2. <repo>/backend/.env.local
    3. <repo>/.env
    4. <repo>/backend/.env

This matches the Next.js convention (`.env.local` is the developer-machine
override) so backend and frontend behave the same way.

Relative paths in ``NEWSLETTER_DEFAULT_WORK_DIR`` resolve against the **backend
dir**, not the current working directory, so ``./cmbdir_newsletter`` always
lands at ``MARS-NewsLetter/backend/cmbdir_newsletter`` regardless of where
``run.py`` is invoked from.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))


def _load_env_files() -> list[Path]:
    """Load .env.local (if any) then .env from repo and backend dirs."""
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        print("python-dotenv is not installed — skipping .env loading. "
              "Run `pip install -r Requirements.txt` to enable it.", file=sys.stderr)
        return []

    candidates = [
        REPO_ROOT / ".env.local",
        BACKEND_DIR / ".env.local",
        REPO_ROOT / ".env",
        BACKEND_DIR / ".env",
    ]
    loaded: list[Path] = []
    for path in candidates:
        if path.is_file():
            # ``override=True`` so the .local files (listed first) win over .env.
            load_dotenv(path, override=True)
            loaded.append(path)
    return loaded


def _resolve_work_dir(raw: str) -> Path:
    """Resolve ``raw`` to an absolute path.

    - ``~``-prefixed paths expand against the user's home.
    - Absolute paths are kept as-is.
    - Relative paths resolve against the **backend dir** so ``./cmbdir_newsletter``
      means ``MARS-NewsLetter/backend/cmbdir_newsletter`` no matter what the
      shell's cwd happens to be.
    """
    expanded = os.path.expanduser(raw)
    p = Path(expanded)
    if not p.is_absolute():
        p = BACKEND_DIR / p
    return p.resolve()


def _ensure_work_dir() -> Path:
    raw = (
        os.getenv("NEWSLETTER_DEFAULT_WORK_DIR")
        or os.getenv("CMBAGENT_DEFAULT_WORK_DIR")
        or "./cmbdir_newsletter"
    )
    work_dir = _resolve_work_dir(raw)
    (work_dir / "logs").mkdir(parents=True, exist_ok=True)
    (work_dir / "sessions").mkdir(parents=True, exist_ok=True)
    # Re-export the canonical absolute path so the rest of the app
    # (core.config, cmbagent, ...) sees the same on-disk location regardless of cwd.
    os.environ["NEWSLETTER_DEFAULT_WORK_DIR"] = str(work_dir)
    os.environ.setdefault("CMBAGENT_DEFAULT_WORK_DIR", str(work_dir))
    return work_dir


def main() -> None:
    loaded = _load_env_files()
    work_dir = _ensure_work_dir()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    log = logging.getLogger("mars-newsletter")

    if loaded:
        log.info("env files loaded: %s", ", ".join(str(p) for p in loaded))
    else:
        log.warning("no .env / .env.local files found — relying purely on shell environment")

    log.info("work_dir ready: %s", work_dir)

    host = os.getenv("HOST", "0.0.0.0")
    try:
        port = int(os.getenv("PORT", "8000"))
    except ValueError:
        log.error("invalid PORT value %r — falling back to 8000", os.getenv("PORT"))
        port = 8000

    # Reload defaults to OFF (production behaviour). Set NEWSLETTER_ENABLE_RELOAD=true
    # explicitly to opt in for development. NEWSLETTER_DEBUG no longer auto-enables
    # reload — debug logging and file-watching are independent concerns.
    enable_reload = os.getenv("NEWSLETTER_ENABLE_RELOAD", "false").lower() == "true"

    log.info(
        "starting server: http://%s:%d (docs http://%s:%d/docs · ws ws://%s:%d/ws/newsletter/{task}/{stage})",
        host, port, host, port, host, port,
    )
    if enable_reload:
        log.warning("auto-reload ENABLED (development) — set NEWSLETTER_ENABLE_RELOAD=false in production")
    else:
        log.info("auto-reload disabled (production mode)")

    # Patterns we never want uvicorn to watch — agent-generated files would
    # otherwise restart the server every time a stage writes output. The
    # work_dir is also added explicitly when it lives under the backend dir
    # (default ``./cmbdir_newsletter``).
    reload_excludes = [
        "**/sessions/**", "**/tasks/**", "**/chats/**",
        "**/data/**", "**/database/**", "**/planning/**", "**/control/**",
        "**/__pycache__/**", "**/*.pyc",
        "*.log", "*.db", "*.sqlite", "*.sqlite3",
        "cmbdir*/**", "cmbagent*/**",
        "backend/cmbdir*/**",
        "**/.cache/**",
    ]
    try:
        rel = work_dir.relative_to(BACKEND_DIR)
        reload_excludes.append(f"{rel}/**")
    except ValueError:
        pass

    import uvicorn  # imported here so a missing dep doesn't crash before logging is set up

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=enable_reload,
        reload_excludes=reload_excludes if enable_reload else None,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        log_config=None,
    )


if __name__ == "__main__":
    main()
