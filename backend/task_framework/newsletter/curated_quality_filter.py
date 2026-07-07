"""Deterministic post-curation quality filter.

Purpose
-------
Even with a strict curator prompt, an LLM will occasionally keep a
2024-dated third-party blog as "Primary source" for a story about GPT-5.
This module runs a small, deterministic pass over the curated markdown
that Stage 3 emits and enforces two hard rules:

1. **Strict date window.** Items whose ``Date:`` line is outside the
   ``[date_from, date_to]`` window, OR whose Primary-source URL contains
   a ``/YYYY/`` path segment whose year is neither ``date_from[:4]`` nor
   ``date_to[:4]``, are dropped. Items with ``date: not stated in snippet``
   are kept only if the URL year is in-window or absent.

2. **Authority-domain preference.** If any URL in ``Also covered by`` is a
   higher-tier source than the current Primary source (per
   ``domain_classifier.classify_deterministic`` plus a small vendor-mapping
   table), swap them so the canonical / vendor / regulator link becomes
   Primary and the third-party press moves to ``Also covered by``.

The filter never adds items and never invents URLs; it only re-orders and
drops. It also appends a short ``## Quality Filter Notes`` block at the
end of the curated markdown so downstream (Stage 4 analyst + Stage 5
scoring) can see what was changed.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from core.logging import get_logger

from .domain_classifier import classify_deterministic

logger = get_logger(__name__)


# Well-known vendor / regulator → official-domain map. Used to
# recognise that (say) any ``openai.com`` URL is the canonical Primary
# for a story that mentions OpenAI or GPT.  This is intentionally small
# — dynamic classification lives in ``domain_classifier``; this table
# only exists to boost the very top of the tier ladder so the swap-rule
# is reliable for the flagship vendors readers will notice most.
_VENDOR_OFFICIAL_DOMAINS: Tuple[str, ...] = (
    "openai.com",
    "anthropic.com",
    "deepmind.google",
    "blog.google",
    "ai.google.dev",
    "ai.meta.com",
    "about.fb.com",
    "blogs.microsoft.com",
    "microsoft.com",
    "aws.amazon.com",
    "blogs.nvidia.com",
    "nvidia.com",
    "mistral.ai",
    "cohere.com",
    "huggingface.co",
    "stability.ai",
    "x.ai",
    "sec.gov",
    "fda.gov",
    "europa.eu",
    "ec.europa.eu",
    "ftc.gov",
    "whitehouse.gov",
    "nist.gov",
    "arxiv.org",
    "nature.com",
    "science.org",
)

# Tier priority for the swap decision. Higher = more authoritative.
_TIER_RANK: Dict[str, int] = {
    "official": 4,
    "authority": 3,
    "neutral": 2,
    "unknown": 1,
}


# Regex helpers — kept module-level so they compile once.
_ITEM_HEADER_RE = re.compile(r"^###\s+(?P<title>.+?)\s*$")
_DATE_LINE_RE = re.compile(r"^-\s*\*\*Date\*\*\s*:\s*(?P<date>.+?)\s*$", re.I)
_PRIMARY_LINE_RE = re.compile(
    r"^(?P<indent>-\s*\*\*Primary source\*\*\s*:\s*)(?P<url>\S+)(?P<rest>.*)$",
    re.I,
)
_ALSO_LINE_RE = re.compile(
    r"^(?P<indent>-\s*\*\*Also covered by\*\*\s*:\s*)(?P<urls>.+?)\s*$",
    re.I,
)
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s,)>]+")
_URL_YEAR_RE = re.compile(r"/(19|20)(\d{2})/")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _domain_of(url: str) -> str:
    """Return the lowercased netloc of ``url``, stripped of leading ``www.``."""
    try:
        netloc = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return netloc[4:] if netloc.startswith("www.") else netloc


def _classify_domain(url: str) -> str:
    """Classify ``url``'s domain into ``official | authority | neutral | unknown``.

    First checks the vendor short-list, then falls back to the deterministic
    layer of ``domain_classifier``. The LLM layer is intentionally NOT called
    here — this filter runs synchronously on every curated item and must stay
    cheap. Unknown domains simply keep the LLM-side ordering (i.e. no swap).
    """
    d = _domain_of(url)
    if not d:
        return "unknown"
    for official in _VENDOR_OFFICIAL_DOMAINS:
        if d == official or d.endswith("." + official):
            return "official"
    tier = classify_deterministic(d)
    return tier or "unknown"


def _tier_rank(url: str) -> int:
    return _TIER_RANK.get(_classify_domain(url), 1)


def _url_year_ok(url: str, years_in_window: List[str]) -> Optional[bool]:
    """Return True/False if URL has a year segment (``/YYYY/``) in/out of window.

    Returns ``None`` when the URL has no year segment — the caller then falls
    back to date-line parsing.
    """
    m = _URL_YEAR_RE.search(url or "")
    if not m:
        return None
    year = m.group(1) + m.group(2)
    return year in years_in_window


def _date_in_window(
    date_str: str, date_from: str, date_to: str
) -> Optional[bool]:
    """True if ``date_str`` is in ``[date_from, date_to]``. None if unparseable."""
    s = (date_str or "").strip().strip("`'\"")
    if not s or "not stated" in s.lower():
        return None
    m = _ISO_DATE_RE.match(s[:10])
    if not m:
        return None
    return date_from <= s[:10] <= date_to


def _split_items(md: str) -> Tuple[str, List[Tuple[str, List[str]]], str]:
    """Split curated markdown into ``(preamble, items, tail)``.

    Each item is ``(header_line, body_lines)`` where ``header_line`` starts
    with ``### `` and body_lines are the lines until the next ``### `` or
    ``## `` boundary. Non-item content before the first ``###`` is preamble;
    trailing sections that start with ``##`` (e.g. Coverage Notes) are tail.
    """
    lines = (md or "").splitlines()
    items: List[Tuple[str, List[str]]] = []
    preamble: List[str] = []
    tail: List[str] = []
    current: Optional[Tuple[str, List[str]]] = None
    in_tail = False

    for line in lines:
        if in_tail:
            tail.append(line)
            continue
        if _ITEM_HEADER_RE.match(line):
            if current is not None:
                items.append(current)
            current = (line, [])
            continue
        # A new top-level ``## `` heading AFTER we've seen items marks the tail
        # (Coverage Notes / Curation Stats). Before any items, keep as preamble.
        if line.startswith("## ") and items:
            if current is not None:
                items.append(current)
                current = None
            tail.append(line)
            in_tail = True
            continue
        if current is None:
            preamble.append(line)
        else:
            current[1].append(line)

    if current is not None:
        items.append(current)

    return ("\n".join(preamble), items, "\n".join(tail))


def _extract_urls_from_also_line(line: str) -> List[str]:
    return _URL_IN_TEXT_RE.findall(line or "")


def _rebuild_primary_line(template_line: str, new_url: str) -> str:
    """Preserve ``- **Primary source**: `` prefix + trailing note, swap URL."""
    m = _PRIMARY_LINE_RE.match(template_line)
    if not m:
        return template_line
    return f"{m.group('indent')}{new_url}{m.group('rest')}"


def _rebuild_also_line(indent: str, urls: List[str]) -> str:
    if not urls:
        return ""
    return f"{indent}{', '.join(urls)}"


def _apply_authority_swap(
    body_lines: List[str],
) -> Tuple[List[str], Optional[Tuple[str, str]]]:
    """If Also-covered has a higher-tier URL than Primary, swap them.

    Returns ``(new_body_lines, swap_report_or_None)``. The report is
    ``(old_primary_domain, new_primary_domain)`` for logging.
    """
    primary_idx: Optional[int] = None
    also_idx: Optional[int] = None
    primary_url = ""
    also_urls: List[str] = []
    also_indent = ""

    for i, ln in enumerate(body_lines):
        pm = _PRIMARY_LINE_RE.match(ln)
        if pm and primary_idx is None:
            primary_idx = i
            # Trim trailing punctuation so tier lookup is clean.
            primary_url = pm.group("url").rstrip(".,;:!?'\"]>)")
            continue
        am = _ALSO_LINE_RE.match(ln)
        if am and also_idx is None:
            also_idx = i
            also_indent = am.group("indent")
            also_urls = [
                u.rstrip(".,;:!?'\"]>)") for u in _extract_urls_from_also_line(am.group("urls"))
            ]

    if primary_idx is None or also_idx is None or not also_urls:
        return body_lines, None

    primary_tier = _tier_rank(primary_url)
    best_also_url = max(also_urls, key=_tier_rank)
    best_also_tier = _tier_rank(best_also_url)

    if best_also_tier <= primary_tier:
        return body_lines, None

    # Swap. New Also-covered = old Primary + (all also except best).
    new_body = list(body_lines)
    new_body[primary_idx] = _rebuild_primary_line(body_lines[primary_idx], best_also_url)
    remaining = [u for u in also_urls if u != best_also_url] + [primary_url]
    # Dedupe while preserving order.
    seen: set = set()
    deduped = []
    for u in remaining:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    new_body[also_idx] = _rebuild_also_line(also_indent, deduped)

    return new_body, (_domain_of(primary_url), _domain_of(best_also_url))


def _item_should_drop(
    body_lines: List[str],
    date_from: str,
    date_to: str,
    years_in_window: List[str],
) -> Optional[str]:
    """Return a reason string if the item should be dropped, else None."""
    date_str = ""
    primary_url = ""
    for ln in body_lines:
        dm = _DATE_LINE_RE.match(ln)
        if dm and not date_str:
            date_str = dm.group("date")
            continue
        pm = _PRIMARY_LINE_RE.match(ln)
        if pm and not primary_url:
            primary_url = pm.group("url").rstrip(".,;:!?'\"]>)")

    date_verdict = _date_in_window(date_str, date_from, date_to)
    if date_verdict is False:
        return f"date out of window ({date_str})"

    url_verdict = _url_year_ok(primary_url, years_in_window)
    if url_verdict is False:
        return f"URL year out of window ({primary_url})"

    return None


def apply_quality_filter(
    curated_md: str, *, date_from: str, date_to: str
) -> Tuple[str, Dict[str, object]]:
    """Enforce strict date + authority rules on the curated markdown.

    Returns ``(cleaned_markdown, report)``. The report includes counts of
    dropped items, authority swaps, and per-item reasons. The cleaned
    markdown has a ``## Quality Filter Notes`` block appended so the
    downstream analyst can see what changed.
    """
    if not (curated_md or "").strip():
        return curated_md, {"kept": 0, "dropped": 0, "swaps": 0}

    yr_from = (date_from or "")[:4]
    yr_to = (date_to or "")[:4]
    years_in_window = sorted({y for y in (yr_from, yr_to) if y})

    preamble, items, tail = _split_items(curated_md)

    kept: List[Tuple[str, List[str]]] = []
    dropped: List[Tuple[str, str]] = []  # (title, reason)
    swaps: List[Tuple[str, str, str]] = []  # (title, old_domain, new_domain)

    for header, body in items:
        title = ""
        hm = _ITEM_HEADER_RE.match(header)
        if hm:
            title = hm.group("title").strip()

        drop_reason = _item_should_drop(body, date_from, date_to, years_in_window)
        if drop_reason:
            dropped.append((title, drop_reason))
            continue

        new_body, swap = _apply_authority_swap(body)
        if swap is not None:
            swaps.append((title, swap[0], swap[1]))
        kept.append((header, new_body))

    # Reassemble.
    out_parts: List[str] = []
    if preamble.strip():
        out_parts.append(preamble.rstrip())
    for header, body in kept:
        out_parts.append(header)
        out_parts.extend(body)
    if tail.strip():
        out_parts.append(tail.rstrip())

    # Append quality-filter notes.
    notes: List[str] = ["", "## Quality Filter Notes"]
    notes.append(f"- Deterministic post-curation filter applied for window {date_from} → {date_to}.")
    notes.append(f"- Items kept: {len(kept)}")
    notes.append(f"- Items dropped for out-of-window date/URL: {len(dropped)}")
    if dropped:
        notes.append("  Dropped:")
        for t, r in dropped[:20]:
            notes.append(f"    - {t or '(untitled)'} — {r}")
        if len(dropped) > 20:
            notes.append(f"    - … and {len(dropped) - 20} more")
    notes.append(f"- Authority-preference swaps (Also→Primary): {len(swaps)}")
    if swaps:
        for t, old, new in swaps[:20]:
            notes.append(f"    - {t or '(untitled)'}: {old or '?'} → {new or '?'}")
        if len(swaps) > 20:
            notes.append(f"    - … and {len(swaps) - 20} more")

    cleaned = "\n".join(out_parts).rstrip() + "\n" + "\n".join(notes) + "\n"

    report: Dict[str, object] = {
        "kept": len(kept),
        "dropped": len(dropped),
        "swaps": len(swaps),
        "dropped_items": [{"title": t, "reason": r} for t, r in dropped],
        "swaps_items": [
            {"title": t, "old_primary_domain": old, "new_primary_domain": new}
            for t, old, new in swaps
        ],
        "date_from": date_from,
        "date_to": date_to,
    }
    logger.info(
        "curated_quality_filter_applied",
        kept=len(kept),
        dropped=len(dropped),
        swaps=len(swaps),
    )
    return cleaned, report
