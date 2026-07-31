"""Render a structured ``ReportDocument`` to standalone HTML.

The JSON document is the single source of truth; both this HTML view and the
PDF are generated from it so they never drift. Broken links (flagged by the
validation node with ``ok = False``) are rendered as inert, struck-through
text so the reader is never handed a dead link.
"""

from __future__ import annotations

import html as _html
import re
from typing import Any, Dict, List

from .state import ReportDocument, ReportLink, ReportSection

try:  # optional — nicer inline formatting when available
    import markdown as _markdown  # type: ignore
except Exception:  # pragma: no cover
    _markdown = None

_MD_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")


def _link_ok(links: List[ReportLink], url: str) -> bool:
    for l in links:
        if l.get("url") == url:
            return l.get("ok", True)
    return True


def _render_inline_links(content: str, links: List[ReportLink]) -> str:
    """Replace markdown links with anchors, disabling broken ones."""
    def _sub(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        if _link_ok(links, url):
            return (
                f'<a href="{_html.escape(url, quote=True)}" '
                f'target="_blank" rel="noopener noreferrer">{_html.escape(label)}</a>'
            )
        return f'<span class="broken-link" title="Unreachable source">{_html.escape(label)}</span>'

    return _MD_LINK_RE.sub(_sub, content)


def _content_to_html(content: str, links: List[ReportLink]) -> str:
    content = _render_inline_links(content or "", links)
    if _markdown is not None:
        # markdown has already-escaped anchors; use 'extra' for tables/lists.
        return _markdown.markdown(content, extensions=["extra", "sane_lists"])
    # Minimal fallback: paragraphs + line breaks, escape everything except our anchors.
    blocks = [b.strip() for b in content.split("\n\n") if b.strip()]
    return "\n".join(f"<p>{b}</p>" for b in blocks)


def _render_section(sec: ReportSection, depth: int = 2, index: int | None = None) -> str:
    """Render one section.

    Top-level sections (``depth == 2``) become presentation "cards" with a
    numbered pill; nested subsections render inline within their parent card so
    the layout reads like slides rather than a flat document.
    """
    title = _html.escape(sec.get("title", ""))
    sec_id = _html.escape(sec.get("id", ""), quote=True)
    is_card = depth == 2

    inner: List[str] = []
    if is_card:
        pill = f'<span class="card-num">{index:02d}</span>' if index is not None else ""
        inner.append(f'<h2 class="card-title">{pill}<span>{title}</span></h2>')
    else:
        tag = f"h{min(depth, 6)}"
        inner.append(f'<{tag} class="sub-title">{title}</{tag}>')

    body = sec.get("content", "")
    if body:
        inner.append(f'<div class="section-body">{_content_to_html(body, sec.get("links", []))}</div>')

    sources = [l for l in sec.get("links", []) if l.get("url")]
    if sources:
        inner.append('<div class="sources"><span class="sources-label">Sources</span><ul>')
        for l in sources:
            url = _html.escape(l.get("url", ""), quote=True)
            text = _html.escape(l.get("text") or l.get("url") or "")
            if l.get("ok", True):
                inner.append(
                    f'<li><a href="{url}" target="_blank" rel="noopener noreferrer">{text}</a></li>'
                )
            else:
                inner.append(f'<li class="broken-link">{text} (unreachable)</li>')
        inner.append("</ul></div>")

    for sub in sec.get("subsections", []) or []:
        inner.append(_render_section(sub, depth + 1))

    wrapper_class = "card" if is_card else "subsection"
    return f'<section id="{sec_id}" class="{wrapper_class}">\n' + "\n".join(inner) + "\n</section>"


def _build_toc(sections: List[ReportSection]) -> str:
    items = []
    for i, sec in enumerate(sections, start=1):
        sid = _html.escape(sec.get("id", ""), quote=True)
        title = _html.escape(sec.get("title", ""))
        items.append(
            f'<li><a href="#{sid}"><span class="toc-num">{i:02d}</span>{title}</a></li>'
        )
    return '<nav class="toc"><h2>Contents</h2><ol>' + "\n".join(items) + "</ol></nav>"


_CSS = """
:root {
  --fg:#14213d; --muted:#5b6478; --accent:#1a4f9e; --accent-2:#0e2548;
  --border:#e2e7f0; --broken:#b00020; --bg:#f4f6fb; --card:#ffffff;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  color: var(--fg); background: var(--bg); margin: 0; line-height: 1.65;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 880px; margin: 0 auto; padding: 0 20px 64px; }

/* ── Cover hero ─────────────────────────────────────────────── */
header.report-head {
  background: linear-gradient(135deg, var(--accent-2) 0%, var(--accent) 100%);
  color: #fff; padding: 64px 20px 56px; margin-bottom: 40px;
  box-shadow: 0 8px 24px rgba(14,37,72,.18);
}
header.report-head .head-inner { max-width: 880px; margin: 0 auto; }
header.report-head .eyebrow {
  text-transform: uppercase; letter-spacing: .18em; font-size: .72rem;
  font-weight: 600; opacity: .8; margin-bottom: 14px;
}
header.report-head h1 { margin: 0 0 10px; font-size: 2.4rem; line-height: 1.15; font-weight: 800; }
header.report-head .subtitle { color: #d7e0f2; font-size: 1.1rem; font-style: italic; }
header.report-head .meta {
  color: #c4d1ea; font-size: .82rem; margin-top: 22px;
  display: flex; flex-wrap: wrap; gap: 8px 18px;
}
header.report-head .meta span { display: inline-flex; align-items: center; }

/* ── Table of contents ──────────────────────────────────────── */
nav.toc {
  background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  padding: 22px 26px; margin-bottom: 36px; box-shadow: 0 2px 10px rgba(20,33,61,.05);
}
nav.toc h2 {
  margin: 0 0 12px; font-size: .8rem; text-transform: uppercase;
  letter-spacing: .12em; color: var(--muted);
}
nav.toc ol { margin: 0; padding: 0; list-style: none; }
nav.toc li { margin: 2px 0; }
nav.toc a {
  color: var(--fg); text-decoration: none; display: flex; align-items: baseline;
  gap: 12px; padding: 7px 8px; border-radius: 8px; transition: background .15s;
}
nav.toc a:hover { background: #eef3fb; color: var(--accent); }
.toc-num { color: var(--accent); font-weight: 700; font-variant-numeric: tabular-nums; font-size: .85rem; }

/* ── Section cards ──────────────────────────────────────────── */
section.card {
  background: var(--card); border: 1px solid var(--border); border-radius: 16px;
  padding: 30px 34px; margin-bottom: 26px;
  box-shadow: 0 3px 14px rgba(20,33,61,.06); scroll-margin-top: 20px;
}
h2.card-title {
  display: flex; align-items: center; gap: 14px; margin: 0 0 18px;
  font-size: 1.4rem; font-weight: 700; color: var(--accent-2); line-height: 1.25;
}
.card-num {
  flex: 0 0 auto; width: 40px; height: 40px; border-radius: 10px;
  background: linear-gradient(135deg, var(--accent-2), var(--accent));
  color: #fff; font-size: .95rem; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center;
  font-variant-numeric: tabular-nums;
}
section.subsection { margin: 20px 0 0; padding: 0; }
.sub-title { font-size: 1.08rem; color: var(--accent); margin: 18px 0 8px; font-weight: 650; }

.section-body { font-size: 1rem; color: #24304a; }
.section-body p { margin: 0 0 14px; }
.section-body a { color: var(--accent); text-decoration: none; border-bottom: 1px solid #bcd0ee; }
.section-body a:hover { border-bottom-color: var(--accent); }
.section-body ul, .section-body ol { padding-left: 1.3em; }
.section-body table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: .92rem; }
.section-body th, .section-body td { border: 1px solid var(--border); padding: 7px 10px; text-align: left; }
.section-body th { background: #eef3fb; font-weight: 600; }
.broken-link { color: var(--broken); text-decoration: line-through; cursor: not-allowed; }

/* ── Sources ────────────────────────────────────────────────── */
.sources { margin-top: 18px; padding-top: 14px; border-top: 1px dashed var(--border); }
.sources-label {
  display: inline-block; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: .1em; font-size: .68rem; margin-bottom: 6px;
}
.sources ul { margin: 4px 0 0; padding-left: 1.2em; font-size: .86rem; }
.sources li { margin: 2px 0; }
.sources a { color: var(--accent); word-break: break-word; }

footer.report-foot {
  text-align: center; color: var(--muted); font-size: .78rem;
  margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border);
}

@media (max-width: 600px) {
  header.report-head h1 { font-size: 1.8rem; }
  section.card { padding: 22px 20px; }
}
"""


def render_html(doc: ReportDocument) -> str:
    title = _html.escape(doc.get("title") or "Newsletter")
    subtitle = _html.escape(doc.get("subtitle") or "")
    meta: Dict[str, Any] = doc.get("meta") or {}
    meta_bits = []
    for key in ("industries", "audience", "coverage", "generated_at"):
        if meta.get(key):
            label = key.replace("_", " ").title()
            meta_bits.append(f"<span><strong>{label}:</strong>&nbsp;{_html.escape(str(meta[key]))}</span>")
    sections = doc.get("sections") or []

    body = "\n".join(_render_section(s, 2, index=i) for i, s in enumerate(sections, start=1))
    toc = _build_toc(sections) if len(sections) > 1 else ""
    coverage = _html.escape(str(meta.get("coverage") or ""))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{_CSS}</style>
</head>
<body>
<header class="report-head">
  <div class="head-inner">
    <div class="eyebrow">Industry Intelligence Briefing</div>
    <h1>{title}</h1>
    {f'<div class="subtitle">{subtitle}</div>' if subtitle else ''}
    {f'<div class="meta">{"".join(meta_bits)}</div>' if meta_bits else ''}
  </div>
</header>
<div class="wrap">
{toc}
{body}
<footer class="report-foot">Generated by MARS-NewsLetter{f' · {coverage}' if coverage else ''}</footer>
</div>
</body>
</html>"""


def document_to_markdown(doc: ReportDocument) -> str:
    """Flatten the structured document back to markdown (drives the PDF)."""
    lines: List[str] = []
    if doc.get("title"):
        lines.append(f"# {doc['title']}")
    if doc.get("subtitle"):
        lines.append(f"_{doc['subtitle']}_")
    lines.append("")

    def _emit(sec: ReportSection, depth: int) -> None:
        lines.append(f"{'#' * min(depth, 6)} {sec.get('title', '')}")
        lines.append("")
        if sec.get("content"):
            lines.append(sec["content"].strip())
            lines.append("")
        ok_links = [l for l in sec.get("links", []) if l.get("url") and l.get("ok", True)]
        if ok_links:
            lines.append("**Sources:** " + " · ".join(
                f"[{l.get('text') or l['url']}]({l['url']})" for l in ok_links
            ))
            lines.append("")
        for sub in sec.get("subsections", []) or []:
            _emit(sub, depth + 1)

    for sec in doc.get("sections") or []:
        _emit(sec, 2)
    return "\n".join(lines).strip() + "\n"
