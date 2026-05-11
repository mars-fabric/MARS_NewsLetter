"""Markdown → PDF rendering with a multi-backend fallback.

Order of attempts:
  1. **WeasyPrint** — preferred; preserves clickable links, headings, tables,
     and the generated TOC.
  2. **fpdf2**       — fallback; minimal styling but no system dependencies.

If both fail we raise; the caller surfaces the error to the user instead of
silently producing nothing.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PdfResult:
    pdf_path: Optional[str]
    success: bool
    backend: Optional[str] = None
    error: Optional[str] = None


_BASE_CSS = """
@page { size: A4; margin: 22mm 18mm 22mm 18mm; }
body { font-family: 'Liberation Sans', 'Helvetica', sans-serif; color: #1a1a1a; line-height: 1.45; font-size: 10.5pt; }
h1 { font-size: 22pt; color: #102040; border-bottom: 2px solid #102040; padding-bottom: 6pt; margin-top: 0; }
h2 { font-size: 15pt; color: #102040; margin-top: 18pt; border-bottom: 1px solid #c7d0e0; padding-bottom: 3pt; }
h3 { font-size: 12.5pt; color: #1f3a6b; margin-top: 14pt; }
h4 { font-size: 11pt; color: #2a4a8a; }
p, li { font-size: 10.5pt; }
a { color: #1a4f9e; text-decoration: none; }
a:hover { text-decoration: underline; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; }
th, td { border: 1px solid #c7d0e0; padding: 5pt 7pt; text-align: left; vertical-align: top; }
th { background: #eef2fa; font-weight: 600; }
code { background: #f3f5fa; padding: 1pt 3pt; border-radius: 2pt; font-family: 'Liberation Mono', monospace; font-size: 9.5pt; }
pre { background: #f3f5fa; padding: 8pt; border-radius: 3pt; overflow-x: auto; }
blockquote { border-left: 3px solid #c7d0e0; margin: 6pt 0; padding: 2pt 10pt; color: #444; }
hr { border: none; border-top: 1px solid #c7d0e0; margin: 12pt 0; }
.cover { text-align: center; padding: 40mm 0 20mm; }
.cover h1 { border-bottom: none; font-size: 26pt; }
.cover .meta { color: #555; font-size: 11pt; margin-top: 8pt; }
.toc { font-size: 10pt; color: #333; }
"""


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

    for line in markdown_text.splitlines():
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


def _markdown_to_html(md_text: str, title: str) -> str:
    import markdown as md_lib

    body = md_lib.markdown(
        md_text,
        extensions=["extra", "tables", "toc", "sane_lists", "nl2br"],
        output_format="html5",
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_html_escape(title)}</title></head>
<body>
<div class="cover">
  <h1>{_html_escape(title)}</h1>
</div>
<hr>
{body}
</body></html>"""


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
         .replace('"', "&quot;").replace("'", "&#39;")
    )


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", title.strip())[:60]
    return s.strip("_") or "newsletter"


def render_pdf(*, markdown_text: str, output_dir: str, title: str) -> PdfResult:
    """Render the given markdown to a PDF at ``<output_dir>/<slug>.pdf``."""
    out_dir = Path(os.path.expanduser(output_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slugify(title)}.pdf"

    # WeasyPrint first
    try:
        html = _markdown_to_html(markdown_text, title)
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
