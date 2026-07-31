"""Typed state for the Stage-5 dynamic report builder (MD → JSON → HTML + PDF).

This replaces the legacy review/score/critique graph. The pipeline takes the
long Stage-4 markdown draft, breaks it into a structured JSON document (sections
with content + links + subsections), enhances each section with an LLM pass,
validates every link, then renders both an HTML view (for the browser) and a
PDF (for download).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class ReportLink(TypedDict, total=False):
    text: str
    url: str
    ok: bool          # populated by the link-validation node
    status: Optional[int]
    tier: Optional[str]


class ReportSection(TypedDict, total=False):
    id: str
    title: str
    level: int                    # heading depth (1 = top, 2 = sub, ...)
    content: str                  # markdown body (no heading line)
    links: List[ReportLink]
    subsections: List["ReportSection"]


class ReportDocument(TypedDict, total=False):
    title: str
    subtitle: str
    meta: Dict[str, Any]          # audience, coverage window, generated_at, ...
    sections: List[ReportSection]


class Stage5ReportState(TypedDict, total=False):
    # ── inputs ──────────────────────────────────────────────────────────────
    work_dir: str
    setup: Dict[str, Any]
    draft: str                    # Stage-4 markdown
    curated: str                  # Stage-3 curated markdown (link allow-list)
    config: Dict[str, Any]
    cost_events: List[Dict[str, Any]]

    # ── intermediate ────────────────────────────────────────────────────────
    document: ReportDocument      # structured JSON document
    link_report: Dict[str, Any]   # aggregate link-validation summary

    # ── outputs ─────────────────────────────────────────────────────────────
    report_json: Dict[str, Any]   # final serialisable document (single source of truth)
    html: Optional[str]
    pdf_path: Optional[str]
    pdf_backend: Optional[str]
    pdf_error: Optional[str]
    output_files: List[str]
    node_timings: Dict[str, float]
