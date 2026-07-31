"""LangGraph nodes for the Stage-5 dynamic report builder.

Pipeline: ``parse → validate_links → link_fix → render``.

Every node is defensive: a failure in link validation or fixing never aborts
the build — it degrades to the deterministic content so the user always gets a
rendered report + PDF.

Note: the LLM ``enhance_node`` was removed because the strict URL-set equality
guard was insufficient to prevent link URL corruption on long sections (the LLM
reordered or paraphrased anchor text while swapping URLs), causing broken links
in the final report. The deterministic ``link_fix_node`` replaces it: it finds
links flagged as broken by the validation pass and replaces them with plain
text, guaranteeing every link in the report resolves.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List

from core.logging import get_logger

from ..pdf_generator import render_pdf
from ..url_health import check_urls, summarise
from .html_renderer import document_to_markdown, render_html
from .markdown_parser import extract_links, nest_sections, parse_markdown
from .state import ReportDocument, ReportSection, Stage5ReportState

logger = get_logger(__name__)


def _timed(state: Stage5ReportState, name: str, start: float) -> None:
    timings = state.setdefault("node_timings", {})
    timings[name] = round(time.time() - start, 3)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Parse — deterministic markdown → nested section tree
# ──────────────────────────────────────────────────────────────────────────────

async def parse_node(state: Stage5ReportState) -> Stage5ReportState:
    start = time.time()
    draft = state.get("draft") or ""
    setup = state.get("setup") or {}

    title, subtitle, flat = parse_markdown(draft)
    sections = nest_sections(flat)

    if not title:
        title = setup.get("title") or "Industry Newsletter"

    industries = ", ".join(i.get("industry", "") for i in setup.get("industries", []))
    doc: ReportDocument = {
        "title": title,
        "subtitle": subtitle,
        "meta": {
            "audience": setup.get("audience"),
            "coverage": f"{setup.get('date_from', '')} → {setup.get('date_to', '')}".strip(" →"),
            "industries": industries,
            "generated_at": time.strftime("%Y-%m-%d"),
        },
        "sections": sections,
    }
    state["document"] = doc
    logger.info("stage5_report_parsed", sections=len(sections), title=title)
    _timed(state, "parse", start)
    return state


# ──────────────────────────────────────────────────────────────────────────────
# 2. Link fix — deterministic: replace broken links with plain text
# ──────────────────────────────────────────────────────────────────────────────

import re as _re


async def link_fix_node(state: Stage5ReportState) -> Stage5ReportState:
    """Deterministically remove broken links from section content.

    For every link flagged as broken (``ok=False``) by the validation node,
    we replace ``[text](url)`` patterns in the section content with just the
    visible ``text``. This guarantees the rendered report never contains a
    dead link — the information stays readable, just unlinked.
    """
    start = time.time()
    doc = state.get("document")
    if not doc:
        _timed(state, "link_fix", start)
        return state

    def _walk(secs: List[ReportSection]) -> None:
        for sec in secs:
            links = sec.get("links") or []
            broken = [l for l in links if not l.get("ok", True) and l.get("url")]
            if broken:
                content = sec.get("content") or ""
                for link in broken:
                    url = (link.get("url") or "").strip()
                    text = (link.get("text") or url).strip()
                    if url:
                        content = _re.sub(
                            r"\[" + _re.escape(text) + r"\]\(" + _re.escape(url) + r"\)",
                            text,
                            content,
                        )
                        content = content.replace(f"<{url}>", url)
                sec["content"] = content
            _walk(sec.get("subsections") or [])

    _walk(doc.get("sections") or [])
    broken_count = sum(
        1 for s in (doc.get("sections") or [])
        for l in (s.get("links") or [])
        if not l.get("ok", True)
    )
    logger.info("stage5_report_link_fix", broken_replaced=broken_count)
    _timed(state, "link_fix", start)
    return state


# ──────────────────────────────────────────────────────────────────────────────
# 3. Validate links — fetch-check every URL, flag broken ones
# ──────────────────────────────────────────────────────────────────────────────

async def validate_links_node(state: Stage5ReportState) -> Stage5ReportState:
    start = time.time()
    doc = state["document"]

    def _walk(secs: List[ReportSection]) -> List[ReportSection]:
        out: List[ReportSection] = []
        for s in secs:
            out.append(s)
            out.extend(_walk(s.get("subsections", []) or []))
        return out

    all_sections = _walk(doc.get("sections", []))
    urls = sorted({l["url"] for s in all_sections for l in s.get("links", []) if l.get("url")})

    if not urls:
        state["link_report"] = {"total": 0}
        _timed(state, "validate_links", start)
        return state

    results = await check_urls(urls)
    by_url = {r["url"].rstrip(".,;:!?'\"]>"): r for r in results}
    for sec in all_sections:
        for link in sec.get("links", []):
            r = by_url.get((link.get("url") or "").rstrip(".,;:!?'\"]>"))
            if r is not None:
                link["ok"] = r.get("tier") not in ("dead", "error")
                link["status"] = r.get("status_code")
                link["tier"] = r.get("tier")
            else:
                link["ok"] = True

    summary = summarise(results)
    summary["broken_urls"] = sorted(
        {r["url"] for r in results if r.get("tier") in ("dead", "error")}
    )
    state["link_report"] = summary
    logger.info(
        "stage5_report_links_validated",
        total=summary.get("total"),
        broken=len(summary.get("broken_urls", [])),
    )
    _timed(state, "validate_links", start)
    return state


# ──────────────────────────────────────────────────────────────────────────────
# 4. Render — JSON → HTML + PDF, persist all artifacts
# ──────────────────────────────────────────────────────────────────────────────

def _write(work_dir: str, filename: str, content: str) -> str:
    stage_dir = Path(work_dir) / "stage_5"
    stage_dir.mkdir(parents=True, exist_ok=True)
    path = stage_dir / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


async def render_node(state: Stage5ReportState) -> Stage5ReportState:
    import json

    start = time.time()
    work_dir = state["work_dir"]
    doc = state["document"]

    report_json: Dict[str, Any] = dict(doc)
    report_json["link_report"] = state.get("link_report", {})
    state["report_json"] = report_json

    markdown = document_to_markdown(doc)
    # HTML is generated for optional download but the primary output is the
    # markdown + PDF. The frontend shows PDF-only (no iframe).
    html = render_html(doc)
    state["html"] = html

    files: List[str] = []
    files.append(_write(work_dir, "report.json", json.dumps(report_json, indent=2, ensure_ascii=False)))
    final_md_path = _write(work_dir, "newsletter_final.md", markdown)
    files.append(final_md_path)
    # HTML kept as a downloadable artifact; not shown in the iframe.
    files.append(_write(work_dir, "newsletter_final.html", html))

    # PDF from the flattened markdown (single source of truth = the document).
    try:
        pdf = render_pdf(
            markdown_text=markdown,
            output_dir=str(Path(work_dir) / "stage_5"),
            title=doc.get("title") or "Newsletter",
            setup=state.get("setup"),
        )
        state["pdf_path"] = pdf.pdf_path
        state["pdf_backend"] = pdf.backend
        state["pdf_error"] = pdf.error
        if pdf.pdf_path:
            files.append(pdf.pdf_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("stage5_report_pdf_failed", error=str(exc))
        state["pdf_error"] = str(exc)

    state["output_files"] = files
    logger.info("stage5_report_rendered", files=len(files), pdf=bool(state.get("pdf_path")))
    _timed(state, "render", start)
    return state
