"""Markdown → PDF rendering with a multi-backend fallback.

Order of attempts:
  1. **WeasyPrint** — preferred; preserves clickable links, headings, tables,
     and the generated TOC.
  2. **fpdf2**       — fallback; minimal styling but no system dependencies.

Citation rendering: every ``[<visible text>](<url>)`` is rewritten so the PDF
shows ONLY the visible text as a clickable hyperlink — the bare URL never
appears in the rendered output. This is the "hidden URL" style: links remain
clickable but the document reads like a professional newsletter rather than a
list of raw URLs. Reference list at the end keeps the URLs for citation
auditing.

If both backends fail we raise; the caller surfaces the error.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PdfResult:
    pdf_path: Optional[str]
    success: bool
    backend: Optional[str] = None
    error: Optional[str] = None


_BASE_CSS = """
@page {
    size: A4;
    margin: 22mm 18mm 24mm 18mm;
    @bottom-right {
        content: "Page " counter(page) " of " counter(pages);
        font-size: 9pt;
        color: #667;
    }
    @bottom-left {
        content: string(doc-title);
        font-size: 9pt;
        color: #667;
    }
}
@page :first {
    margin: 0;
    @bottom-right { content: none; }
    @bottom-left { content: none; }
}
html, body {
    font-family: 'Georgia', 'Liberation Serif', serif;
    color: #1a1a1a;
    line-height: 1.55;
    font-size: 11pt;
}
h1 {
    font-family: 'Helvetica', 'Liberation Sans', sans-serif;
    string-set: doc-title content();
    font-size: 22pt;
    color: #0e2548;
    border-bottom: 2px solid #0e2548;
    padding-bottom: 6pt;
    margin-top: 0;
    page-break-before: always;
}
h2 {
    font-family: 'Helvetica', 'Liberation Sans', sans-serif;
    font-size: 14.5pt;
    color: #0e2548;
    margin-top: 18pt;
    border-bottom: 1px solid #c7d0e0;
    padding-bottom: 3pt;
}
h3 {
    font-family: 'Helvetica', 'Liberation Sans', sans-serif;
    font-size: 12pt;
    color: #1f3a6b;
    margin-top: 14pt;
}
h4 { font-size: 10.5pt; color: #2a4a8a; font-style: italic; }
p, li { font-size: 10.5pt; }
a {
    color: #1a4f9e;
    text-decoration: none;
    border-bottom: 1px dotted #8fb1e0;
}
a:hover { border-bottom: 1px solid #1a4f9e; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; }
th, td { border: 1px solid #c7d0e0; padding: 5pt 7pt; text-align: left; vertical-align: top; }
th { background: #eef2fa; font-weight: 600; }
code { background: #f3f5fa; padding: 1pt 3pt; border-radius: 2pt; font-family: 'Liberation Mono', monospace; font-size: 9.5pt; }
pre { background: #f3f5fa; padding: 8pt; border-radius: 3pt; overflow-x: auto; }
blockquote { border-left: 3px solid #c7d0e0; margin: 6pt 0; padding: 2pt 10pt; color: #444; }
hr { border: none; border-top: 1px solid #c7d0e0; margin: 12pt 0; }

.cover {
    height: 297mm;
    padding: 50mm 22mm 40mm;
    background: linear-gradient(180deg, #0e2548 0%, #1a4f9e 60%, #1a4f9e 100%);
    color: #fff;
    page-break-after: always;
}
.cover h1 {
    border-bottom: none;
    color: #fff;
    font-size: 32pt;
    margin-top: 0;
    page-break-before: avoid;
}
.cover .subtitle { color: #cfd8e6; font-size: 13pt; margin-top: 8pt; font-style: italic; }
.cover .meta { color: #cfd8e6; font-size: 11pt; margin-top: 16mm; }
.cover .meta div { margin: 3pt 0; }
.cover .footer { position: absolute; bottom: 30mm; color: #aab8ce; font-size: 9pt; font-style: italic; }

.toc {
    page-break-after: always;
    padding: 12mm 0;
}
.toc h2 { border-bottom: 2px solid #0e2548; padding-bottom: 4pt; }
.toc ul { list-style: none; padding: 0; }
.toc li { font-size: 11pt; margin: 4pt 0; border-bottom: 1px dotted #c7d0e0; padding-bottom: 2pt; }
.toc a { color: #1a4f9e; border-bottom: none; }

.refs {
    font-size: 9.5pt;
    color: #444;
    page-break-before: always;
}
.refs h2 { border-bottom: 2px solid #0e2548; }
.refs ol { padding-left: 20pt; }
.refs li { margin: 3pt 0; }
.refs a { word-break: break-all; }

.quality-score {
    margin: 14pt 0;
    padding: 10pt 14pt;
    background: #eef4fb;
    border-left: 4px solid #1a4f9e;
    border-radius: 2pt;
}
"""

_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BARE_URL_RE = re.compile(r"<(https?://[^>\s]+)>")


def _rewrite_citations(md_text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Hide raw URLs in citations. Return ``(rewritten_md, citation_list)``.

    Each `[visible](url)` becomes just `[visible]` with a numbered superscript
    citation marker (e.g. ``[1]``). The original URL/text pair is recorded for
    the References section the renderer appends at the end.
    Bare ``<https://...>`` URLs are dropped from visible text but kept in refs.
    """
    citations: List[Tuple[str, str]] = []
    seen: dict[str, int] = {}

    def _link_sub(m: re.Match) -> str:
        visible = (m.group(1) or "").strip()
        url = (m.group(2) or "").strip().rstrip(".,;:!?'\"]>")
        if not url:
            return visible
        if url in seen:
            n = seen[url]
        else:
            n = len(citations) + 1
            seen[url] = n
            citations.append((visible or _short_domain(url), url))
        return f"[{visible}](#ref{n}){{.cite}}<sup>[{n}](#ref{n})</sup>"

    def _bare_sub(m: re.Match) -> str:
        url = m.group(1).strip().rstrip(".,;:!?'\"]>")
        if not url:
            return ""
        if url in seen:
            n = seen[url]
        else:
            n = len(citations) + 1
            seen[url] = n
            citations.append((_short_domain(url), url))
        return f"<sup>[{n}](#ref{n})</sup>"

    rewritten = _LINK_RE.sub(_link_sub, md_text)
    rewritten = _BARE_URL_RE.sub(_bare_sub, rewritten)
    return rewritten, citations


def _short_domain(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1) if m else url


def _build_toc(md_text: str) -> str:
    """Extract `## N. <Title>` headings into a clickable ToC block."""
    items = []
    for m in re.finditer(r"^##\s+(\d+\.\s+[^\n]+)$", md_text, flags=re.MULTILINE):
        heading = m.group(1).strip()
        anchor = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
        items.append(f'<li><a href="#{anchor}">{_html_escape(heading)}</a></li>')
    if not items:
        return ""
    return (
        '<div class="toc"><h2>Contents</h2><ul>'
        + "\n".join(items)
        + "</ul></div>"
    )


def _build_cover(title: str, subtitle: str, meta_lines: List[str]) -> str:
    meta = "".join(f"<div>{_html_escape(m)}</div>" for m in meta_lines)
    return (
        '<div class="cover">'
        f'<h1>{_html_escape(title)}</h1>'
        f'<div class="subtitle">{_html_escape(subtitle)}</div>'
        f'<div class="meta">{meta}</div>'
        '<div class="footer">Generated by MARS-NewsLetter · powered by mars_cmbagent + LangGraph</div>'
        '</div>'
    )


def _build_refs(citations: List[Tuple[str, str]]) -> str:
    if not citations:
        return ""
    items = []
    for n, (label, url) in enumerate(citations, start=1):
        safe_url = _html_escape(url)
        safe_label = _html_escape(label)
        items.append(
            f'<li id="ref{n}"><a href="{safe_url}">{safe_label}</a> '
            f'<span style="color:#888;">— {safe_url}</span></li>'
        )
    return (
        '<div class="refs"><h2>References</h2><ol>'
        + "\n".join(items)
        + "</ol></div>"
    )


def _render_with_weasyprint(html: str, out_path: Path) -> None:
    from weasyprint import HTML, CSS  # type: ignore
    HTML(string=html, base_url=str(out_path.parent)).write_pdf(
        target=str(out_path), stylesheets=[CSS(string=_BASE_CSS)]
    )


def _render_with_fpdf(markdown_text: str, out_path: Path, title: str) -> None:
    from fpdf import FPDF  # type: ignore

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, _safe_text(title), ln=1)
    pdf.set_font("Helvetica", "", 10.5)

    # Drop markdown link syntax for fpdf fallback (no hyperlink support here).
    plain = _LINK_RE.sub(r"\1", markdown_text)
    plain = _BARE_URL_RE.sub("", plain)

    for line in plain.splitlines():
        if not line.strip():
            pdf.ln(3)
            continue
        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 8, _safe_text(line[2:]))
            pdf.set_font("Helvetica", "", 10.5)
        elif line.startswith("## "):
            pdf.set_font("Helvetica", "B", 13)
            pdf.multi_cell(0, 7, _safe_text(line[3:]))
            pdf.set_font("Helvetica", "", 10.5)
        elif line.startswith("### "):
            pdf.set_font("Helvetica", "B", 11.5)
            pdf.multi_cell(0, 6, _safe_text(line[4:]))
            pdf.set_font("Helvetica", "", 10.5)
        elif line.startswith("- ") or line.startswith("* "):
            pdf.multi_cell(0, 5, "• " + _safe_text(line[2:]))
        else:
            pdf.multi_cell(0, 5, _safe_text(line))

    pdf.output(str(out_path))


def _safe_text(s: str) -> str:
    """fpdf2's core fonts can't render arbitrary unicode; downgrade gracefully."""
    return s.encode("latin-1", errors="replace").decode("latin-1")


_SUBTITLE_RE = re.compile(r"^_(.+)_$", re.MULTILINE)


def _extract_title_subtitle(md_text: str, fallback_title: str) -> Tuple[str, str, str]:
    """Pull the leading `# <Title>` line and the first italic subtitle.

    Returns ``(title, subtitle, body_after_title)``. Body keeps everything
    after the title line (and the optional subtitle italic line) so the cover
    block doesn't duplicate them in the body.
    """
    body = md_text
    title = fallback_title
    subtitle = ""
    m = re.match(r"^#\s+([^\n]+)\n", body)
    if m:
        title = m.group(1).strip()
        body = body[m.end():]
    # Optional italic subtitle right after the title
    m2 = re.match(r"^\s*_([^_\n]+)_\s*\n", body)
    if m2:
        subtitle = m2.group(1).strip()
        body = body[m2.end():]
    return title, subtitle, body


def _markdown_to_html(md_text: str, title: str, setup: Optional[dict]) -> str:
    import markdown as md_lib

    title, subtitle, body_md = _extract_title_subtitle(md_text, title)

    setup = setup or {}
    industries = setup.get("industries") or []
    industry_label = ", ".join(
        i.get("industry", "") for i in industries if isinstance(i, dict) and i.get("industry")
    ) or ""
    date_from = setup.get("date_from") or ""
    date_to = setup.get("date_to") or ""
    audience = setup.get("audience") or ""

    cover_meta: List[str] = []
    if industry_label:
        cover_meta.append(f"Industry: {industry_label}")
    if date_from or date_to:
        cover_meta.append(f"Coverage: {date_from} → {date_to}")
    if audience:
        cover_meta.append(f"Audience: {audience}")

    cover = _build_cover(title, subtitle or "Industry intelligence digest", cover_meta)
    toc = _build_toc(body_md)

    body_md_clean, citations = _rewrite_citations(body_md)

    body_html = md_lib.markdown(
        body_md_clean,
        extensions=["extra", "tables", "toc", "sane_lists", "nl2br"],
        output_format="html5",
    )

    refs_html = _build_refs(citations)

    return f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<title>{_html_escape(title)}</title>
</head>
<body>
{cover}
{toc}
<div class="body">{body_html}</div>
{refs_html}
</body></html>"""


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
         .replace('"', "&quot;").replace("'", "&#39;")
    )


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", title.strip())[:60]
    return s.strip("_") or "newsletter"


def render_pdf(
    *,
    markdown_text: str,
    output_dir: str,
    title: str,
    setup: Optional[dict] = None,
) -> PdfResult:
    """Render the given markdown to a PDF at ``<output_dir>/<slug>.pdf``.

    ``setup`` is optional — when provided, it's used to populate the cover
    page (industry, coverage window, audience). The cover is omitted in the
    fpdf2 fallback.
    """
    out_dir = Path(os.path.expanduser(output_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slugify(title)}.pdf"

    # WeasyPrint first
    try:
        html = _markdown_to_html(markdown_text, title, setup)
        _render_with_weasyprint(html, out_path)
        return PdfResult(pdf_path=str(out_path), success=True, backend="weasyprint")
    except Exception as exc:
        logger.warning("pdf_weasyprint_failed", error=str(exc))

    # fpdf fallback
    try:
        _render_with_fpdf(markdown_text, out_path, title)
        return PdfResult(pdf_path=str(out_path), success=True, backend="fpdf2")
    except Exception as exc:
        logger.error("pdf_fpdf_failed", error=str(exc))
        return PdfResult(pdf_path=None, success=False, backend=None, error=str(exc))
