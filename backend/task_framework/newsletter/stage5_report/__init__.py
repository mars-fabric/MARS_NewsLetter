"""Stage-5 dynamic report builder package.

Breaks the long Stage-4 markdown draft into a structured JSON document
(sections + content + links + subsections), enhances each section with an LLM
pass, validates every link, then renders both an HTML view and a PDF from the
single JSON source of truth.

This replaces the legacy ``stage5`` review/score/critique LangGraph.
"""

from __future__ import annotations

from .graph import build_report_graph
from .runner import run_stage_5_report

__all__ = ["run_stage_5_report", "build_report_graph"]
