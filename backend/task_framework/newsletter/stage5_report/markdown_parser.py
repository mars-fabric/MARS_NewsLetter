"""Deterministic markdown → section-tree parser for the Stage-5 report builder.

The LLM structuring node produces the *rich* JSON, but we always run this
deterministic parser first so:

  * we have a reliable fallback if the LLM structuring call fails, and
  * the LLM gets a clean, pre-split outline to work from (cheaper + more
    accurate than asking it to parse raw markdown from scratch).

Output shape mirrors ``state.ReportSection`` but without the LLM enhancement.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .state import ReportLink, ReportSection

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BARE_URL_RE = re.compile(r"(?<!\()\bhttps?://[^\s)\]<>\"']+")


def _slugify(text: str, idx: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return f"{base or 'section'}-{idx}"


def extract_links(text: str) -> List[ReportLink]:
    """Pull markdown + bare links out of a block of text (deduped by URL)."""
    seen: Dict[str, ReportLink] = {}
    for m in _MD_LINK_RE.finditer(text or ""):
        label, url = m.group(1).strip(), m.group(2).rstrip(".,;:!?'\"]>")
        if url not in seen:
            seen[url] = {"text": label, "url": url}
    for m in _BARE_URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(".,;:!?'\"]>")
        if url not in seen:
            seen[url] = {"text": url, "url": url}
    return list(seen.values())


def _split_title_block(md: str) -> Tuple[str, str, str]:
    """Return ``(title, subtitle, remainder)`` from the top of the document.

    The Stage-4 draft starts with ``# <Title>`` optionally followed by a
    ``_coverage line_`` / subtitle before the first ``##`` section heading.
    """
    lines = (md or "").splitlines()
    title, subtitle = "", ""
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines):
        m = _HEADING_RE.match(lines[i])
        if m and len(m.group(1)) == 1:
            title = m.group(2).strip()
            i += 1
    # Subtitle: first non-empty, non-heading line before the next heading.
    j = i
    while j < len(lines):
        stripped = lines[j].strip()
        if not stripped:
            j += 1
            continue
        if _HEADING_RE.match(lines[j]):
            break
        subtitle = stripped.strip("_*").strip()
        j += 1
        break
    remainder = "\n".join(lines[j:])
    return title, subtitle, remainder


def parse_markdown(md: str) -> Tuple[str, str, List[ReportSection]]:
    """Split markdown into ``(title, subtitle, flat_sections)``.

    Sections are split at ``##``-and-deeper headings. Nesting is preserved via
    the ``level`` field; the structuring node folds deeper levels into
    ``subsections``. Here we keep a flat list keyed by heading level.
    """
    title, subtitle, body = _split_title_block(md)

    sections: List[ReportSection] = []
    current: ReportSection | None = None
    buf: List[str] = []
    idx = 0

    def _flush() -> None:
        nonlocal current, buf
        if current is not None:
            content = "\n".join(buf).strip()
            current["content"] = content
            current["links"] = extract_links(content)
            sections.append(current)
        buf = []

    for line in body.splitlines():
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) >= 2:
            _flush()
            idx += 1
            level = len(m.group(1))
            heading = m.group(2).strip()
            current = {
                "id": _slugify(heading, idx),
                "title": heading,
                "level": level,
                "content": "",
                "links": [],
                "subsections": [],
            }
        else:
            if current is None:
                # Ignore whitespace-only preamble before the first heading.
                if not line.strip():
                    continue
                # Real preamble content becomes an intro section.
                current = {
                    "id": _slugify("introduction", 0),
                    "title": "Introduction",
                    "level": 2,
                    "content": "",
                    "links": [],
                    "subsections": [],
                }
            buf.append(line)
    _flush()
    # Drop empty sections that are neither content-bearing nor container
    # headings (a section whose next sibling is deeper is a real parent).
    pruned: List[ReportSection] = []
    for i, s in enumerate(sections):
        has_body = bool((s.get("content") or "").strip() or s.get("links"))
        is_container = (
            i + 1 < len(sections)
            and sections[i + 1].get("level", 2) > s.get("level", 2)
        )
        if has_body or is_container:
            pruned.append(s)
    return title, subtitle, pruned


def nest_sections(flat: List[ReportSection]) -> List[ReportSection]:
    """Fold a flat, level-tagged section list into a nested tree.

    A section becomes a child of the most recent section with a smaller level.
    """
    roots: List[ReportSection] = []
    stack: List[ReportSection] = []
    for sec in flat:
        sec.setdefault("subsections", [])
        level = sec.get("level", 2)
        while stack and stack[-1].get("level", 2) >= level:
            stack.pop()
        if stack:
            stack[-1].setdefault("subsections", []).append(sec)
        else:
            roots.append(sec)
        stack.append(sec)
    return roots
