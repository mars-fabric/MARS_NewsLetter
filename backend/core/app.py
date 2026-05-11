"""FastAPI application factory."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.logging import configure_logging, get_logger

_app: FastAPI | None = None
_log_config: dict = {}


def _ensure_work_dir() -> Path:
    """Make sure the configured work directory and its standard sub-folders exist.

    The work_dir is the on-disk root for everything we produce: per-task stage
    outputs, the logs sub-folder, and the cmbagent sessions tree. Creating it
    on startup means a fresh checkout (or a freshly-pulled docker volume) does
    not fail with FileNotFoundError on the first request.
    """
    base = Path(settings.expanded_work_dir).resolve()
    for sub in ("logs", "sessions"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def _default_log_file() -> str:
    base = _ensure_work_dir()
    return str(base / "logs" / "newsletter-backend.log")


def _recover_stale_running_stages() -> None:
    """If the server died mid-run, mark any orphaned 'running' stages as 'failed'."""
    log = get_logger(__name__)
    try:
        from cmbagent.database.base import init_database, get_db_session
        from cmbagent.database.models import TaskStage
        from datetime import datetime, timezone

        init_database()
        db = get_db_session()
        try:
            stale = db.query(TaskStage).filter(TaskStage.status == "running").all()
            for stage in stale:
                stage.status = "failed"
                stage.error_message = "Server restarted mid-run. Click retry to re-execute."
                stage.completed_at = datetime.now(timezone.utc)
            if stale:
                db.commit()
                log.warning("recovered_stale_stages", count=len(stale))
        finally:
            db.close()
    except Exception as exc:
        log.warning("stale_recovery_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(**_log_config)
    log = get_logger(__name__)
    work_dir = _ensure_work_dir()
    log.info("backend_started",
             log_file=_log_config.get("log_file"),
             work_dir=str(work_dir))

    # Sync provider creds from .env + encrypted vault into cmbagent's ProviderRegistry.
    # ConfigBridge layers vault (UI-set) on top of env (admin-set) so that creds
    # added through the Settings dialog persist across restarts and outrank env.
    try:
        from services.config_bridge import ConfigBridge
        ConfigBridge.sync_all()
    except Exception as exc:
        log.warning("config_bridge_sync_failed", error=str(exc))
        # Fall back to the lightweight env-only sync so we still pick up .env keys.
        try:
            from services.provider_bridge import sync_providers_from_env
            sync_providers_from_env()
        except Exception as inner:
            log.warning("provider_env_sync_failed", error=str(inner))

    _recover_stale_running_stages()
    yield


def create_app() -> FastAPI:
    global _app, _log_config

    log_file = os.getenv("LOG_FILE") or _default_log_file()
    _log_config = {
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "json_output": os.getenv("LOG_JSON", "false").lower() == "true",
        "log_file": log_file,
    }
    configure_logging(**_log_config)

    app = FastAPI(title=settings.app_title, version=settings.app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _app = app
    return app


def get_app() -> FastAPI:
    global _app
    if _app is None:
        _app = create_app()
    return _app
