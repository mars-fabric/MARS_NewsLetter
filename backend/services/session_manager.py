"""Tiny in-memory + on-disk session persistence for NewsLetter task setup.

The cmbagent ORM owns the canonical stage status / output rows. This module is
responsible only for the *user-supplied setup payload* (industries, source mode,
URLs, etc.) which doesn't naturally fit any cmbagent table.

Persistence lives at ``<work_dir>/sessions/<session_id>/tasks/<task_id>/setup.json``
so it survives server restarts.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from core.logging import get_logger

logger = get_logger(__name__)

_SETUP_FILENAME = "setup.json"
_lock = threading.Lock()


def _setup_path(work_dir: str) -> Path:
    return Path(work_dir) / _SETUP_FILENAME


def save_setup(work_dir: str, setup: Dict[str, Any]) -> None:
    path = _setup_path(work_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with path.open("w", encoding="utf-8") as f:
            json.dump(setup, f, indent=2, default=str)
    logger.info("setup_saved", work_dir=work_dir)


def load_setup(work_dir: str) -> Optional[Dict[str, Any]]:
    path = _setup_path(work_dir)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("setup_load_failed", path=str(path), error=str(exc))
        return None


def update_setup(work_dir: str, **changes: Any) -> Dict[str, Any]:
    current = load_setup(work_dir) or {}
    current.update(changes)
    save_setup(work_dir, current)
    return current
