"""Stage 5 support package.

The legacy 22-node LangGraph review/score-card flow that used to live here has
been removed. The active Stage-5 render pipeline now lives in
:mod:`task_framework.newsletter.stage5_report`.

Only the shared litellm wrapper survives in this package because Stage 4 and
Stage 5 both import it:

    from ..stage5.llm_client import acomplete, default_model
"""

from __future__ import annotations

from .llm_client import acomplete, acomplete_json, default_model

__all__ = ["acomplete", "acomplete_json", "default_model"]
