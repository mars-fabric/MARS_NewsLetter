"""Model Configuration API — exposes available models and per-workflow defaults.

This mirrors PaperPulse's ``/api/models/*`` surface so the NewsLetter UI can
fetch the same model list (sourced from cmbagent's ``model_config.yaml``) and
let the user override it from the browser. When ``mars_cmbagent`` is not
installed we fall back to a small static list so the UI still renders.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/models", tags=["Models"])


# Static fallback shown when cmbagent isn't importable. Keeps the dropdown
# usable in dev / smoke-test environments without the pip package.
_STATIC_FALLBACK: Dict[str, Any] = {
    "available_models": [
        {"value": "gpt-4o", "label": "GPT-4o"},
        {"value": "gpt-4.1-2025-04-14", "label": "GPT-4.1"},
        {"value": "o3-mini-2025-01-31", "label": "o3-mini"},
        {"value": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4"},
        {"value": "gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
    ],
    "global_defaults": {
        "default_model": "gpt-4o",
        "planner_model": "gpt-4o",
        "plan_reviewer_model": "o3-mini",
        "researcher_model": "gpt-4.1-2025-04-14",
        "orchestration_model": "gpt-4.1-2025-04-14",
        "formatter_model": "o3-mini",
    },
    "workflow_defaults": {},
}


def _registry():
    """Return the cmbagent ModelRegistry, or ``None`` when unavailable."""
    try:
        from cmbagent.config.model_registry import get_model_registry  # type: ignore
        return get_model_registry()
    except Exception as exc:
        logger.debug("cmbagent_model_registry_unavailable", error=str(exc))
        return None


@router.get("/config")
async def get_model_config() -> Dict[str, Any]:
    """Full config: available_models + global_defaults + workflow_defaults."""
    reg = _registry()
    if reg is None:
        return _STATIC_FALLBACK
    return reg.get_full_config()


@router.get("/available")
async def get_available_models() -> List[Dict[str, str]]:
    """Flat list of ``{value, label}`` model options for UI dropdowns."""
    reg = _registry()
    if reg is None:
        return _STATIC_FALLBACK["available_models"]
    return reg.get_available_models()


@router.post("/reload")
async def reload_model_config() -> Dict[str, str]:
    """Hot-reload ``model_config.yaml`` without restarting the server."""
    try:
        from cmbagent.config.model_registry import reload_model_registry  # type: ignore
        reload_model_registry()
        logger.info("model_config_reloaded_via_api")
        return {"status": "reloaded"}
    except Exception as exc:
        logger.warning("model_config_reload_failed", error=str(exc))
        return {"status": "unavailable", "error": str(exc)}
