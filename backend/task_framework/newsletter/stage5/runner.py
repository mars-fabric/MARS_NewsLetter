"""Entry point that orchestrates the Stage 5 LangGraph.

This module deliberately mirrors the signature and return shape of
``helpers.run_stage_5`` so the existing background-task scheduler in
``routers/newsletter.py`` can swap implementations behind a single flag
without changes to the orchestration layer.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.logging import get_logger

from ..helpers import merge_overrides, stage_def
from .graph import build_stage5_graph
from .state import Stage5State

logger = get_logger(__name__)


# Lazy singleton — building the graph is cheap, but reusing avoids per-call work.
_GRAPH = None


def _graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_stage5_graph()
    return _GRAPH


async def run_stage_5_langgraph(
    *,
    work_dir: str,
    setup: Dict[str, Any],
    draft: str,
    curated: str,
    mode_override: Optional[Any] = None,  # accepted for signature parity; ignored
    config_overrides: Optional[Dict[str, Any]] = None,
    cost_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[Dict[str, Any], str, List[str]]:
    """LangGraph-based replacement for ``helpers.run_stage_5``.

    Inputs and outputs match the legacy contract:
      * Reads Stage-3 (``curated``) and Stage-4 (``draft``) artifacts.
      * Writes ``stage_5/`` artifacts to disk.
      * Returns ``(shared_state_update, primary_text, output_files)``.

    ``mode_override`` is accepted but ignored — the LangGraph pipeline has no
    cmbagent agent modes. ``config_overrides`` is currently passed into the
    state for nodes that read model overrides.
    """
    started = time.time()
    config = merge_overrides(setup, 5, config_overrides) or {}

    initial_state: Stage5State = {
        "work_dir": work_dir,
        "setup": setup,
        "draft": draft,
        "curated": curated,
        "config": config,
        "cost_events": [],
        "node_timings": {},
        "verification_notes": [],
    }

    try:
        result = await _graph().ainvoke(initial_state)
    except Exception as exc:  # noqa: BLE001
        logger.exception("stage5_langgraph_failed")
        raise

    duration = round(time.time() - started, 2)
    logger.info(
        "stage5_langgraph_done",
        duration_s=duration,
        files=len(result.get("output_files") or []),
        overall=(result.get("aggregate") or {}).get("overall_score"),
    )

    # Forward per-node cost events to the caller's cost_callback if provided.
    if cost_callback:
        for ev in result.get("cost_events") or []:
            try:
                cost_callback(ev)
            except Exception:  # noqa: BLE001
                logger.exception("stage5_cost_callback_failed")

    final_text = result.get("final_with_score") or result.get("final_markdown") or ""
    shared_update: Dict[str, Any] = {
        stage_def(5)["shared_key"]: final_text,
        "verification_notes": result.get("verification_notes") or [],
        "pdf_path": result.get("pdf_path"),
        "pdf_backend": result.get("pdf_backend"),
        "pdf_error": result.get("pdf_error"),
        "score_card": result.get("score_card") or {},
        "stage5_aggregate": result.get("aggregate") or {},
        "stage5_dashboard": result.get("visualization_payload") or {},
        "stage5_dashboard_metrics": result.get("dashboard_metrics") or {},
        "stage5_url_verification": result.get("url_verification") or {},
        "stage5_critic": {
            "corrections": result.get("critic_corrections") or [],
            "tone_pass": result.get("critic_tone_pass"),
            "tone_notes": result.get("critic_tone_notes"),
        },
        "stage5_ddgs_findings": result.get("ddgs_findings") or [],
        "stage5_timings": result.get("node_timings") or {},
    }
    return shared_update, final_text, list(result.get("output_files") or [])
