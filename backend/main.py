"""MARS-NewsLetter — FastAPI entry point + per-stage WebSocket streaming."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import WebSocket

# Make ``backend`` importable as the project root regardless of how uvicorn is launched.
sys.path.insert(0, str(Path(__file__).parent))

from core.app import create_app  # noqa: E402
from core.logging import get_logger  # noqa: E402
from execution import console_capture  # noqa: E402
from routers import register_routers  # noqa: E402
from websocket.events import send_ws_event  # noqa: E402

ws_logger = get_logger("websocket")

app = create_app()
register_routers(app)


@app.websocket("/ws/newsletter/{task_id}/{stage_num}")
async def newsletter_stage_ws(websocket: WebSocket, task_id: str, stage_num: int) -> None:
    """Push stage status transitions (``stage_completed`` / ``stage_failed``)
    for one (task, stage) pair.

    Console lines are *not* sent over the socket — the frontend pulls them
    incrementally from ``GET /stages/{n}/console?since=N`` (see PaperPulse's
    pattern). Keeping the WS focused on low-rate state events makes both
    sides simpler and prevents log duplication when the WS reconnects.
    """
    await websocket.accept()
    buf_key = f"{task_id}:{stage_num}"
    stale_cycles = 0
    STALE_THRESHOLD = 5

    try:
        await send_ws_event(websocket, "status", {
            "message": f"Connected to stage {stage_num}", "stage_num": stage_num,
        }, run_id=task_id)

        while True:
            await asyncio.sleep(1)

            try:
                from routers.newsletter import _get_db, _stage_repo, _running, _running_lock  # type: ignore
                from cmbagent.database.models import WorkflowRun  # type: ignore

                db = _get_db()
                try:
                    run = db.query(WorkflowRun).filter(WorkflowRun.id == task_id).first()
                    session_id = run.session_id if run else "newsletter"
                    repo = _stage_repo(db, session_id=session_id)
                    stages = repo.list_stages(parent_run_id=task_id)
                    stage = next((s for s in stages if s.stage_number == stage_num), None)
                    if stage is None:
                        continue

                    if stage.status == "completed":
                        await send_ws_event(websocket, "stage_completed",
                                            {"stage_num": stage_num, "stage_name": stage.stage_name},
                                            run_id=task_id)
                        break

                    if stage.status == "failed":
                        await send_ws_event(websocket, "stage_failed",
                                            {"stage_num": stage_num, "error": stage.error_message or "stage failed"},
                                            run_id=task_id)
                        break

                    if stage.status == "running":
                        # Watchdog: if there's no active background task AND no
                        # new lines have been written since the last tick, the
                        # process likely died (uvicorn restart, OOM kill, ...).
                        # Mark the stage failed so the user can retry instead
                        # of staring at a permanently-running spinner.
                        with _running_lock:
                            bg = _running.get(buf_key)
                        has_active = bg is not None and not bg.done()
                        recent_lines = bool(console_capture.get_lines(buf_key, since_index=0))
                        if not has_active and not recent_lines:
                            stale_cycles += 1
                        else:
                            stale_cycles = 0

                        if stale_cycles >= STALE_THRESHOLD:
                            stage.status = "failed"
                            stage.error_message = "Execution was interrupted (no active process). Click retry."
                            stage.completed_at = datetime.now(timezone.utc)
                            db.commit()
                            await send_ws_event(websocket, "stage_failed",
                                                {"stage_num": stage_num, "error": stage.error_message},
                                                run_id=task_id)
                            break
                finally:
                    db.close()
            except Exception as exc:
                ws_logger.debug("ws_db_check_failed", task=task_id, stage=stage_num, error=str(exc))

    except Exception as ws_err:
        if "disconnect" in str(ws_err).lower() or "close" in str(ws_err).lower():
            ws_logger.debug("ws_disconnected", task=task_id, stage=stage_num)
        else:
            ws_logger.warning("ws_error", task=task_id, stage=stage_num, error=str(ws_err))
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
