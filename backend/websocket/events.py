"""WebSocket send helper with retry on transient failures."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from core.logging import get_logger

logger = get_logger(__name__)

_MAX_RETRIES = 2
_BACKOFF = 0.1


async def send_ws_event(
    ws: WebSocket,
    event_type: str,
    data: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> bool:
    try:
        if ws.client_state != WebSocketState.CONNECTED:
            return False
    except Exception:
        pass

    msg = {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data": data or {},
    }
    if run_id:
        msg["run_id"] = run_id
    if session_id:
        msg["session_id"] = session_id

    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            await ws.send_json(msg)
            return True
        except Exception as e:
            last_err = e
            if isinstance(e, RuntimeError) and "close message has been sent" in str(e):
                break
            try:
                if ws.client_state != WebSocketState.CONNECTED:
                    break
            except Exception:
                break
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_BACKOFF * (2 ** attempt))

    logger.warning("ws_send_failed", event_type=event_type, error=str(last_err))
    return False
