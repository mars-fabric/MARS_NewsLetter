"""Stage-5 dynamic report builder — public entry point.

Replaces the legacy review/score/critique LangGraph. Takes the Stage-4
markdown draft and produces a structured JSON document, an HTML view, and a
PDF — all driven from one JSON source of truth.

Signature mirrors ``helpers.run_stage_5`` so the orchestration layer and the
background scheduler in ``routers/newsletter.py`` need no changes:

    (shared_state_update, primary_text, output_files)
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.logging import get_logger

from ..helpers import merge_overrides, stage_def
from .graph import report_graph
from .state import Stage5ReportState

logger = get_logger(__name__)


async def run_stage_5_report(
    *,
    work_dir: str,
    setup: Dict[str, Any],
    draft: str,
    curated: str,
    mode_override: Optional[Any] = None,  # accepted for signature parity; ignored
    config_overrides: Optional[Dict[str, Any]] = None,
    cost_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[Dict[str, Any], str, List[str]]:
    started = time.time()
    config = merge_overrides(setup, 5, config_overrides) or {}

    initial: Stage5ReportState = {
        "work_dir": work_dir,
        "setup": setup,
        "draft": draft,
        "curated": curated,
        "config": config,
        "cost_events": [],
        "node_timings": {},
    }

    result = await report_graph().ainvoke(initial)

    if cost_callback:
        for ev in result.get("cost_events") or []:
            try:
                cost_callback(ev)
            except Exception:  # noqa: BLE001
                logger.exception("stage5_report_cost_callback_failed")

    report_json = result.get("report_json") or {}
    # The 'final' shared key now carries the flattened markdown so the stage
    # content endpoint can serve it as plain text (newsletter_final.md).
    # HTML is still written to disk for optional download but is no longer the
    # primary artifact surfaced to the UI.
    pdf_path = result.get("pdf_path") or ""
    shared_update: Dict[str, Any] = {
        stage_def(5)["shared_key"]: pdf_path,  # 'final' — pdf path (readable reference)
        "report_json": report_json,
        "report_html": result.get("html") or "",
        "link_report": result.get("link_report") or {},
        "pdf_path": pdf_path,
        "pdf_backend": result.get("pdf_backend"),
        "pdf_error": result.get("pdf_error"),
        "stage5_timings": result.get("node_timings") or {},
    }
    # primary_text: return the markdown so the stage content endpoint has text
    # to show (falls back to the newsletter_final.md file on disk via stage_def).
    primary_text = f"PDF generated: {pdf_path}" if pdf_path else ""
    logger.info(
        "stage5_report_done",
        duration_s=round(time.time() - started, 2),
        files=len(result.get("output_files") or []),
        pdf=bool(pdf_path),
    )
    return shared_update, primary_text, list(result.get("output_files") or [])
