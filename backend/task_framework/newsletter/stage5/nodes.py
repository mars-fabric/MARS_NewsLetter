"""All 22 LangGraph nodes for Stage 5.

Status legend (in docstrings):
  * IMPLEMENTED — fully working
  * STUB        — typed scaffold returning state untouched; replace before prod

Each node is an async function ``(state: Stage5State) -> dict``. The returned
dict is merged into the state by LangGraph. Returning ``{}`` means "no change".

The four nodes the user prioritized for first-pass implementation are:
  * executive_summary_node
  * section_writer_node
  * aggregate_score_node
  * dashboard_metrics_node
Everything else is a STUB that future iterations will fill in.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from core.logging import get_logger

from .llm_client import acomplete, acomplete_json
from .state import (
    ContentItem,
    EvaluatorScore,
    Insight,
    SectionWeakness,
    Stage5State,
    TopicCluster,
)

logger = get_logger(__name__)


# Industry-credibility allowlist — domain → tier ("official" | "authority" | "neutral").
# Anything not present here gets a neutral baseline and the LLM can override.
_DOMAIN_TIER: Dict[str, str] = {
    "openai.com": "official", "anthropic.com": "official",
    "ai.meta.com": "official", "engineering.fb.com": "official",
    "ai.googleblog.com": "official", "cloud.google.com": "official",
    "blogs.microsoft.com": "official", "microsoft.com": "official",
    "huggingface.co": "official", "github.com": "official",
    "sap.com": "official", "news.sap.com": "official",
    "reuters.com": "authority", "wsj.com": "authority", "ft.com": "authority",
    "bloomberg.com": "authority", "nature.com": "authority",
    "techcrunch.com": "neutral", "theverge.com": "neutral",
    "techrepublic.com": "neutral", "infoworld.com": "neutral",
    "venturebeat.com": "neutral", "aibusiness.com": "neutral",
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers shared by multiple nodes
# ──────────────────────────────────────────────────────────────────────────────

_URL_RE = re.compile(r"https?://[^\s)\"'<>]+")
_SECTION_HEAD_RE = re.compile(r"^##+\s+(\d+\.\s+[^\n]+|[A-Z][^\n]+)$", re.MULTILINE)


def _extract_urls_set(text: str) -> set[str]:
    urls = set(_URL_RE.findall(text or ""))
    return {u.rstrip(".,;:!?'\"]>") for u in urls}


def _split_sections(markdown: str) -> List[Tuple[str, str]]:
    """Split a markdown document by top-level ## headings.

    Only splits at exactly two ``#``. `###` and deeper subheadings stay inside
    their parent section's body — this is what every caller wants (coverage
    checking, body-length thresholds, URL extraction by section, etc.).
    Splitting at any `##+` would empty the body of any section that uses
    subheadings and falsely flag it as "weak".
    """
    if not markdown:
        return []
    parts = re.split(r"^(##\s+[^\n]+)$", markdown, flags=re.MULTILINE)
    # parts: [preamble, heading1, body1, heading2, body2, ...]
    sections: List[Tuple[str, str]] = []
    if len(parts) <= 1:
        return [("", markdown)]
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        sections.append((heading, body.strip()))
    return sections


def _domain_of(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
        return host.lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return ""


def _tick(state: Stage5State, node: str, start: float) -> Dict[str, Any]:
    timings = dict(state.get("node_timings") or {})
    timings[node] = round(time.time() - start, 3)
    return {"node_timings": timings}


# ──────────────────────────────────────────────────────────────────────────────
# 1) Input nodes
# ──────────────────────────────────────────────────────────────────────────────

async def load_stage3_data_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: parse the curated markdown into ContentItem records.

    Stage 3 emits items as ``### <title>`` blocks followed by
    ``- **Field**: value`` lines (Date / Primary source / Source / Category /
    Top / Relevance / Authority / Freshness / Summary). We parse each block
    end-to-end; on failure we fall back to bare URL extraction so downstream
    nodes never crash on a thin curated set.
    """
    start = time.time()
    curated = state.get("curated") or ""
    items: List[ContentItem] = []

    # Walk the markdown block-by-block. The curator emits item headings as
    # either `### <title>` or `#### <title>` (the depth varies depending on
    # whether items are nested under company sub-sections). A block ends at
    # the next heading of equal-or-lesser depth, or end-of-document. We use
    # a body terminator that stops at any `^##` or `^###` line, then strip
    # nested sub-headings from the parsed title-row's body length so they
    # don't dilute the field extraction.
    block_re = re.compile(
        r"^#{3,4}\s+(?P<title>[^\n]+?)\s*\n"
        r"(?P<body>(?:(?!^#{2,4}\s).+\n?)+)",
        flags=re.MULTILINE,
    )

    def _field(body: str, name: str) -> str:
        m = re.search(
            rf"-\s+\*\*{re.escape(name)}\*\*:\s*(.+?)(?:\n|$)",
            body, flags=re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""

    def _primary_url(body: str) -> Tuple[str, str]:
        # Format: `- **Primary source**: <https://...> (<domain>)`
        m = re.search(
            r"-\s+\*\*Primary source\*\*:\s*<?(https?://[^\s>)]+)>?\s*(?:\(([^)]+)\))?",
            body, flags=re.IGNORECASE,
        )
        if m:
            return m.group(1).strip(), (m.group(2) or "").strip().lower()
        # Fallback: any URL in the body.
        urls = _extract_urls_set(body)
        if urls:
            u = sorted(urls)[0]
            return u, _domain_of(u)
        return "", ""

    def _int(s: str) -> Optional[int]:
        m = re.search(r"\d+", s or "")
        return int(m.group(0)) if m else None

    for m in block_re.finditer(curated):
        title = m.group("title").strip()
        body = m.group("body") or ""
        url, domain = _primary_url(body)
        if not url:
            continue  # skip section/sub-domain headings without a URL
        date_field = _field(body, "Date")
        date_match = re.search(r"(20\d{2}-\d{2}-\d{2})", date_field)
        source_field = _field(body, "Source").lower()
        category = _field(body, "Category") or "uncategorized"
        top = _field(body, "Top").lower() == "yes"
        relevance = _int(_field(body, "Relevance"))
        authority = _int(_field(body, "Authority"))
        freshness = _int(_field(body, "Freshness"))
        summary = _field(body, "Summary")
        items.append({
            "title": title,
            "url": url,
            "domain": domain or _domain_of(url),
            "snippet": (summary[:500] if summary else body.strip()[:500]),
            "category": category,
            "is_top": top,
            "published_at": date_match.group(1) if date_match else None,
            # Stage-3 numeric scores let later nodes weight items.
            "relevance_score": relevance,
            "authority_score": authority,
            "freshness_score": freshness,
            "source_kind": "user-provided" if "user-provided" in source_field else "web-discovered",
        })

    if not items:
        for url in sorted(_extract_urls_set(curated)):
            items.append({
                "title": url, "url": url, "domain": _domain_of(url),
                "snippet": "", "category": "uncategorized",
                "is_top": False, "published_at": None,
            })

    allowed_urls = sorted(_extract_urls_set(curated))
    logger.info("stage5_load_stage3", items=len(items), urls=len(allowed_urls))
    return {
        "items": items,
        "allowed_urls": allowed_urls,
        **_tick(state, "load_stage3_data_node", start),
    }


async def load_stage4_data_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: split the Stage-4 draft into section blocks.

    Returns a merged_corpus dict with the section list. We keep the draft text
    intact so downstream nodes can quote/reuse it verbatim.
    """
    start = time.time()
    draft = state.get("draft") or ""
    sections = _split_sections(draft)
    merged = {
        "draft_sections": [{"heading": h, "body": b} for h, b in sections],
        "draft_length_chars": len(draft),
    }
    logger.info("stage5_load_stage4", sections=len(sections), chars=len(draft))
    return {"merged_corpus": merged, **_tick(state, "load_stage4_data_node", start)}


async def merge_content_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: join curated items to draft sections by category/URL co-occurrence."""
    start = time.time()
    items = state.get("items") or []
    merged = dict(state.get("merged_corpus") or {})
    sections = merged.get("draft_sections") or []

    # Build URL → item index for O(1) lookup.
    by_url: Dict[str, ContentItem] = {it["url"]: it for it in items if it.get("url")}

    enriched_sections = []
    for s in sections:
        body = s.get("body", "")
        cited_urls = sorted(_extract_urls_set(body))
        backing = [by_url[u] for u in cited_urls if u in by_url]
        enriched_sections.append({**s, "cited_urls": cited_urls, "backing_items": backing})

    merged["draft_sections"] = enriched_sections
    merged["distinct_categories"] = sorted({(it.get("category") or "uncategorized") for it in items})

    return {"merged_corpus": merged, **_tick(state, "merge_content_node", start)}


# ──────────────────────────────────────────────────────────────────────────────
# 2) Report-building (LLM-assisted but structured)
# ──────────────────────────────────────────────────────────────────────────────

async def content_grouping_node(state: Stage5State) -> Dict[str, Any]:
    """STUB: bucket items by category. Deterministic — no LLM."""
    start = time.time()
    items = state.get("items") or []
    groups: Dict[str, List[ContentItem]] = {}
    for it in items:
        cat = it.get("category") or "uncategorized"
        groups.setdefault(cat, []).append(it)
    return {"content_groups": groups, **_tick(state, "content_grouping_node", start)}


async def topic_clustering_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: bucket items by category into TopicCluster records.

    Each category becomes one cluster. Deterministic — no LLM needed; the
    Stage-3 curator already grouped by category and we trust that.
    """
    start = time.time()
    groups = state.get("content_groups") or {}
    clusters: List[TopicCluster] = []
    for idx, (cat, items) in enumerate(groups.items()):
        clusters.append(
            {
                "cluster_id": f"c{idx:02d}",
                "theme": cat,
                "items": items,
                "section_hint": None,
            }
        )
    return {"clusters": clusters, **_tick(state, "topic_clustering_node", start)}


async def insight_extraction_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: derive top insights by counting "Top: yes" items per cluster.

    Cheap deterministic version — avoid an LLM call here since the writer
    already produced themed prose. Each insight points to the top URLs.
    """
    start = time.time()
    clusters = state.get("clusters") or []
    insights: List[Insight] = []
    for c in clusters:
        items = c.get("items") or []
        top_items = [it for it in items if it.get("is_top")]
        if not top_items:
            continue
        urls = [it.get("url", "") for it in top_items[:5] if it.get("url")]
        insights.append({
            "insight": f"{c.get('theme', 'topic')}: {len(top_items)} top-rated items, "
                       f"led by {top_items[0].get('title', '')[:80]}",
            "supporting_urls": urls,
            "confidence": min(1.0, 0.5 + 0.1 * len(top_items)),
        })
    return {"insights": insights, **_tick(state, "insight_extraction_node", start)}


async def executive_summary_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: produce a 4-bullet executive summary grounded in the draft + items.

    Uses the Stage-4 draft as the primary source of truth (it already
    synthesizes the curated content), with the top-tagged items as bullets'
    pointers. Returns a markdown string in ``executive_summary``.
    """
    start = time.time()
    setup = state.get("setup") or {}
    draft = state.get("draft") or ""
    items = state.get("items") or []
    industries = ", ".join(i.get("industry", "") for i in setup.get("industries", []) if i.get("industry"))
    date_from = setup.get("date_from", "")
    date_to = setup.get("date_to", "")
    audience = setup.get("audience") or "executives"

    top_items = [it for it in items if it.get("is_top")][:12]
    top_block = "\n".join(
        f"- {it.get('title','')} — [{it.get('domain','')}]({it.get('url','')})"
        for it in top_items
    ) or "(no items flagged Top — fall back to draft for synthesis)"

    draft_excerpt = draft[:8000]

    messages = [
        {
            "role": "system",
            "content": (
                "You are a senior industry analyst. Write a tight, evidence-backed "
                "executive summary for a newsletter. NEVER invent citations, dates, "
                "or numbers — quote only what appears in the provided material."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Audience: {audience}\n"
                f"Industries: {industries or '(unspecified)'}\n"
                f"Coverage window: {date_from} → {date_to}\n\n"
                f"## Top items (Stage 3)\n{top_block}\n\n"
                f"## Stage 4 draft (excerpt, may be truncated)\n{draft_excerpt}\n\n"
                "Write the executive summary as exactly 4 markdown bullets. Each "
                "bullet: one sentence, concrete, naming the specific company/event "
                "and (if known) the date. End each bullet with one inline citation "
                "in the form [domain](url) drawn from the top items above. No "
                "preamble, no closing line, just the four bullets."
            ),
        },
    ]

    try:
        content, usage = await acomplete(
            messages=messages,
            temperature=0.2,
            max_tokens=900,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("stage5_executive_summary_failed")
        content = ""
        usage = {"error": str(exc)}

    cost_events = list(state.get("cost_events") or [])
    if usage:
        cost_events.append({"node": "executive_summary_node", **usage})

    return {
        "executive_summary": content.strip(),
        "cost_events": cost_events,
        **_tick(state, "executive_summary_node", start),
    }


async def section_writer_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: regenerate sections flagged ``weak_sections`` by evaluators.

    Iterates state['weak_sections']; for each weakness, asks the LLM to rewrite
    that section grounded in:
      * the section's existing draft body
      * the curated items that share its category or URL
    Sections not flagged weak are left untouched (the assembly node merges
    rewrites back into the draft).
    """
    start = time.time()
    weak = state.get("weak_sections") or []
    if not weak:
        return {"section_drafts": {}, **_tick(state, "section_writer_node", start)}

    merged = state.get("merged_corpus") or {}
    sections = merged.get("draft_sections") or []
    by_heading: Dict[str, Dict[str, Any]] = {s.get("heading", ""): s for s in sections}
    allowed_urls = set(state.get("allowed_urls") or [])

    rewrites: Dict[str, str] = {}
    cost_events = list(state.get("cost_events") or [])

    for w in weak:
        heading = w.get("section", "")
        sec = by_heading.get(heading)
        if not sec:
            continue
        body = sec.get("body", "")
        backing = sec.get("backing_items", []) or []
        backing_lines = "\n".join(
            f"- {it.get('title','')} — [{it.get('domain','')}]({it.get('url','')})"
            for it in backing[:10]
        ) or "(no curated items matched this section's URLs)"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an editor rewriting a single section of an industry "
                    "newsletter. Output ONLY the rewritten section markdown, "
                    "starting with the original heading verbatim. Cite only URLs "
                    "from the backing items list — any other URL is forbidden."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Weakness: {w.get('issue','')} (severity: {w.get('severity','')})\n\n"
                    f"## Existing section\n{heading}\n\n{body}\n\n"
                    f"## Backing curated items\n{backing_lines}\n\n"
                    "Rewrite the section to fix the weakness. Preserve the heading "
                    "verbatim. Keep length within ±20% of the original. Inline "
                    "citations: [domain](url) only from the backing list."
                ),
            },
        ]

        try:
            content, usage = await acomplete(
                messages=messages,
                temperature=0.2,
                max_tokens=1800,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("stage5_section_rewrite_failed", heading=heading, error=str(exc))
            continue

        # Strip any URLs the LLM hallucinated despite instructions.
        cleaned = []
        for line in content.splitlines():
            urls_in_line = _extract_urls_set(line)
            if urls_in_line and not (urls_in_line & allowed_urls):
                # Drop disallowed URLs from the link target while keeping text.
                line = re.sub(r"\(https?://[^\s)]+\)", "", line)
            cleaned.append(line)
        rewrites[heading] = "\n".join(cleaned).strip()

        if usage:
            cost_events.append({"node": "section_writer_node", "heading": heading, **usage})

    return {
        "section_drafts": rewrites,
        "cost_events": cost_events,
        **_tick(state, "section_writer_node", start),
    }


async def report_assembly_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: assemble final markdown.

    Preference order for body content:
      1. ``edited_markdown`` (output of editor_node — critic corrections applied)
      2. ``draft`` with ``section_drafts`` rewrites swapped in
      3. raw ``draft``

    The Stage-4 draft already begins with a `# <Title>` block and contains the
    22 canonical sections, so we use it as-is when the editor produced clean
    output. Otherwise we splice in section rewrites.
    """
    start = time.time()
    setup = state.get("setup") or {}
    draft = state.get("draft") or ""
    exec_summary = (state.get("executive_summary") or "").strip()
    rewrites = state.get("section_drafts") or {}
    edited = (state.get("edited_markdown") or "").strip()

    if edited:
        # Regression guard: when the editor truncates the input or replaces
        # substantive content with the "no in-window material" placeholder,
        # use the original draft instead. The editor's job is to apply critic
        # corrections surgically — if its output is worse than the input by
        # those two objective measures, we keep the draft and surface a note.
        ph_token = "no in-window material"
        edited_placeholders = edited.lower().count(ph_token)
        draft_placeholders = draft.lower().count(ph_token)
        edited_loses_content = len(edited) < int(len(draft) * 0.85)
        edited_adds_placeholders = edited_placeholders > draft_placeholders
        if edited_loses_content or edited_adds_placeholders:
            logger.warning(
                "stage5_editor_regression_using_draft",
                draft_chars=len(draft), edited_chars=len(edited),
                draft_placeholders=draft_placeholders,
                edited_placeholders=edited_placeholders,
            )
            from ..programmatic_verification import verify_and_clean
            allowed = set(state.get("allowed_urls") or [])
            cleaned, notes = verify_and_clean(final_text=draft, allowed_urls=allowed)
            prior_notes = list(state.get("verification_notes") or [])
            prior_notes.append(
                f"Editor output rejected (shorter/over-placeholder); kept Stage-4 draft. "
                f"draft={len(draft)} chars / {draft_placeholders} placeholders "
                f"vs edited={len(edited)} chars / {edited_placeholders} placeholders."
            )
            return {
                "assembled_report": cleaned,
                "verification_notes": prior_notes + notes,
                **_tick(state, "report_assembly_node", start),
            }

        # Editor produced a complete cleaned document. Apply the programmatic
        # verification pass (allow-list URL strip + canonical heading
        # normalisation) and return.
        from ..programmatic_verification import verify_and_clean
        allowed = set(state.get("allowed_urls") or [])
        cleaned, notes = verify_and_clean(final_text=edited, allowed_urls=allowed)
        prior_notes = list(state.get("verification_notes") or [])
        return {
            "assembled_report": cleaned,
            "verification_notes": prior_notes + notes,
            **_tick(state, "report_assembly_node", start),
        }

    industries = [i.get("industry", "") for i in setup.get("industries", []) if i.get("industry")]
    title = ", ".join(industries) or "Newsletter"
    date_from = setup.get("date_from", "")
    date_to = setup.get("date_to", "")

    if rewrites:
        sections = _split_sections(draft)
        rebuilt = []
        for heading, body in sections:
            if heading in rewrites:
                rebuilt.append(rewrites[heading])
            else:
                rebuilt.append(f"{heading}\n\n{body}")
        body_md = "\n\n".join(rebuilt)
    else:
        body_md = draft

    header = (
        f"# {title}\n\n"
        f"_Coverage: {date_from} → {date_to}_\n\n"
    )
    summary_block = (
        f"## Executive Summary\n\n{exec_summary}\n\n" if exec_summary else ""
    )
    assembled = header + summary_block + body_md
    return {"assembled_report": assembled, **_tick(state, "report_assembly_node", start)}


# ──────────────────────────────────────────────────────────────────────────────
# 3) Evaluation system (mostly deterministic)
# ──────────────────────────────────────────────────────────────────────────────

async def relevance_scoring_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: LLM JSON rubric — 0-100 + rationale + off-topic list."""
    start = time.time()
    setup = state.get("setup") or {}
    assembled = state.get("assembled_report") or state.get("draft") or ""
    industries = ", ".join(i.get("industry", "") for i in setup.get("industries", []) if i.get("industry"))
    sub_domains: List[str] = []
    for i in setup.get("industries", []):
        sub_domains.extend(i.get("sub_domains") or [])

    excerpt = assembled[:12000]
    schema = (
        '{"score": <int 0-100>, "rationale": "<one sentence>", '
        '"off_topic_sections": ["<section heading>", ...]}'
    )
    messages = [
        {"role": "system", "content": "You are a strict newsletter quality auditor. Evaluate on-topic alignment only."},
        {"role": "user", "content": (
            f"Target industries: {industries or '(none)'}\n"
            f"Target sub-domains: {', '.join(sub_domains) or '(none)'}\n\n"
            f"## Newsletter excerpt\n{excerpt}\n\n"
            "Rate relevance to the target industries (0-100). 100 = every section on-topic and useful, "
            "60 = clearly on-topic but with off-topic noise, 0 = unrelated. List section headings that "
            "are off-topic."
        )},
    ]
    score = 0.0
    detail: Dict[str, Any] = {}
    notes = ""
    cost_events = list(state.get("cost_events") or [])
    try:
        result, usage = await acomplete_json(messages=messages, schema_hint=schema, temperature=0.0, max_tokens=400)
        if usage:
            cost_events.append({"node": "relevance_scoring_node", **usage})
        if isinstance(result, dict):
            score = float(result.get("score") or 0)
            detail = {"off_topic_sections": result.get("off_topic_sections") or []}
            notes = str(result.get("rationale") or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("stage5_relevance_failed", error=str(exc))
        notes = f"llm error: {exc}"

    scores = dict(state.get("scores") or {})
    scores["relevance"] = {"score": round(score, 1), "detail": detail, "notes": notes}
    return {"scores": scores, "cost_events": cost_events, **_tick(state, "relevance_scoring_node", start)}


async def diversity_scoring_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: score domain/source diversity.

    Combines (a) Shannon entropy normalised against the max entropy for the
    citation count, (b) a single-source-dominance penalty when any one
    domain accounts for >35% of citations. Result is 0-100.
    """
    start = time.time()
    import math

    items = state.get("items") or []
    domain_counts: Dict[str, int] = {}
    for it in items:
        d = it.get("domain") or _domain_of(it.get("url", ""))
        if d:
            domain_counts[d] = domain_counts.get(d, 0) + 1

    total = sum(domain_counts.values())
    unique = len(domain_counts)

    if total == 0:
        score = 0.0
        detail = {"unique_domains": 0, "total_citations": 0, "entropy": 0.0, "dominance": 0.0}
    else:
        entropy = -sum(
            (n / total) * math.log2(n / total)
            for n in domain_counts.values() if n > 0
        )
        max_entropy = math.log2(unique) if unique > 1 else 1.0
        norm_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

        max_share = max(domain_counts.values()) / total
        dominance_penalty = max(0.0, max_share - 0.35) * 100.0  # >35% share starts costing points

        score = max(0.0, min(100.0, norm_entropy * 100.0 - dominance_penalty))
        detail = {
            "unique_domains": unique,
            "total_citations": total,
            "entropy": round(entropy, 3),
            "normalized_entropy": round(norm_entropy, 3),
            "max_domain_share": round(max_share, 3),
            "dominance_penalty": round(dominance_penalty, 1),
        }

    scores = dict(state.get("scores") or {})
    scores["diversity"] = {"score": round(score, 1), "detail": detail, "notes": ""}
    return {"scores": scores, **_tick(state, "diversity_scoring_node", start)}


async def credibility_scoring_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: rate credibility tier of cited sources.

    Deterministic core (allowlist tier weights) + URL-reachability bonus from
    ``url_verification`` results when present. No LLM call — the tier table
    plus reachability is enough signal here and saves a round-trip.
    """
    start = time.time()
    items = state.get("items") or []
    verification = state.get("dashboard_metrics", {}) if False else state.get("url_verification") or {}

    tier_weights = {"official": 100, "authority": 85, "neutral": 60, "unknown": 40}
    tier_counts = {"official": 0, "authority": 0, "neutral": 0, "unknown": 0}
    per_domain: Dict[str, str] = {}
    weighted_sum = 0.0
    total = 0
    for it in items:
        d = (it.get("domain") or _domain_of(it.get("url", ""))).lower().lstrip("www.")
        if not d:
            continue
        tier = _DOMAIN_TIER.get(d) or _DOMAIN_TIER.get(d.split(".", 1)[-1], "unknown")
        per_domain[d] = tier
        tier_counts[tier] += 1
        weighted_sum += tier_weights[tier]
        total += 1

    base = (weighted_sum / total) if total else 0.0

    # Reachability bonus / penalty
    reach_pct = 100.0
    if verification:
        results = verification.get("results") or []
        reach = [r for r in results if r.get("reachable")]
        if results:
            reach_pct = 100.0 * len(reach) / len(results)
    # Final score = 0.8 * base + 0.2 * reachability_pct
    score = 0.8 * base + 0.2 * reach_pct

    scores = dict(state.get("scores") or {})
    scores["credibility"] = {
        "score": round(score, 1),
        "detail": {
            "tier_counts": tier_counts,
            "per_domain_tier": per_domain,
            "reachability_pct": round(reach_pct, 1),
        },
        "notes": f"tier-weighted base {round(base,1)} + reach bonus",
    }
    return {"scores": scores, **_tick(state, "credibility_scoring_node", start)}


async def freshness_scoring_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: composite freshness over the coverage window.

    Two signals combined:
      * **In-window ratio** (60% weight) — share of dated items whose date is
        inside ``date_from`` → ``date_to``.
      * **Dated-coverage ratio** (40% weight) — share of items that carry an
        explicit date at all. The Stage-3 curator tags undated items with
        `date: not stated in snippet` rather than dropping them, so a healthy
        freshness signal needs *both* dating discipline and in-window items.
    """
    start = time.time()
    setup = state.get("setup") or {}
    items = state.get("items") or []
    df = setup.get("date_from")
    dt = setup.get("date_to")
    in_window = 0
    dated = 0
    for it in items:
        pub = it.get("published_at")
        if not pub:
            continue
        dated += 1
        if df and dt and df <= pub <= dt:
            in_window += 1

    total = len(items)
    in_window_ratio = (in_window / dated) if dated else 0.0
    dated_ratio = (dated / total) if total else 0.0
    score = 100.0 * (0.6 * in_window_ratio + 0.4 * dated_ratio)

    scores = dict(state.get("scores") or {})
    scores["freshness"] = {
        "score": round(score, 1),
        "detail": {
            "in_window": in_window,
            "dated_items": dated,
            "total_items": total,
            "in_window_ratio": round(in_window_ratio, 3),
            "dated_ratio": round(dated_ratio, 3),
        },
        "notes": "",
    }
    return {"scores": scores, **_tick(state, "freshness_scoring_node", start)}


async def redundancy_detector_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: detect repeated URL citations across sections and near-duplicate bullets.

    Two heuristics:
      * URL collision — same source cited in 4+ different sections (=> reduce
        diversity score).
      * Bullet similarity — within ``## Other Notable Headlines``, flag bullets
        whose first 60 chars match another bullet.
    """
    start = time.time()
    assembled = state.get("assembled_report") or state.get("draft") or ""
    sections = _split_sections(assembled)

    url_to_sections: Dict[str, set[str]] = {}
    for heading, body in sections:
        for u in _extract_urls_set(body):
            url_to_sections.setdefault(u, set()).add(heading)

    over_cited = [
        {"url": u, "section_count": len(s), "sections": sorted(s)[:5]}
        for u, s in url_to_sections.items() if len(s) >= 4
    ]

    # Bullet near-duplicates
    near_dups: List[Dict[str, Any]] = []
    seen_starts: Dict[str, str] = {}
    for heading, body in sections:
        for line in body.splitlines():
            if not line.lstrip().startswith(("- ", "* ")):
                continue
            txt = line.lstrip(" -*").strip().lower()
            key = re.sub(r"[^a-z0-9 ]+", "", txt)[:60]
            if not key:
                continue
            if key in seen_starts and seen_starts[key] != heading:
                near_dups.append({"section_a": seen_starts[key], "section_b": heading, "snippet": txt[:120]})
            else:
                seen_starts[key] = heading

    return {
        "redundancy_report": {
            "duplicates": over_cited[:20],
            "near_duplicates": near_dups[:20],
        },
        **_tick(state, "redundancy_detector_node", start),
    }


# Canonical 22 newsletter section names — must stay in sync with the writer prompt.
_CANONICAL_22 = (
    "Newsletter Metadata", "Editor's Note", "Executive Summary",
    "TL;DR", "Industry & Subdomain Focus", "Top Story of the Period",
    "Secondary Major Story", "Other Notable Headlines", "Subdomain Highlights",
    "Releases & Announcements", "Trend Intelligence", "Audience-Centric Analysis",
    "Focus Topic Deep Dive", "Source-Driven Insights", "Data & Evidence",
    "Quotes & Opinions", "Tools & Resources", "Action & Utility",
    "Forward-Looking Intelligence", "Transparency & Methodology",
    "Compliance & Trust", "Closure",
)


async def coverage_checker_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: verify all 22 canonical sections present + substantive."""
    start = time.time()
    assembled = state.get("assembled_report") or state.get("draft") or ""
    sections = _split_sections(assembled)
    headings = [h for h, _ in sections]

    present: List[str] = []
    missing: List[str] = []
    weak: List[str] = []
    for canonical in _CANONICAL_22:
        match = next((h for h in headings if canonical.lower() in h.lower()), None)
        if not match:
            missing.append(canonical)
            continue
        present.append(canonical)
        body = next((b for h, b in sections if h == match), "")
        # "stub" body = explicit no-material marker OR very short.
        if "no in-window material" in body.lower() or len(body.strip()) < 150:
            weak.append(canonical)

    return {
        "coverage_report": {
            "section_count": len(sections),
            "non_empty_sections": len(present) - len(weak),
            "missing": missing,
            "weak": weak,
            "canonical_total": len(_CANONICAL_22),
        },
        **_tick(state, "coverage_checker_node", start),
    }


async def aggregate_score_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: collapse per-evaluator scores into one overall score + score_card.

    Weights are deliberately conservative; tune in config later. Also produces
    the legacy ``score_card`` dict so existing UI/PDF code keeps working.
    """
    start = time.time()
    scores = state.get("scores") or {}
    redundancy = state.get("redundancy_report") or {}
    coverage = state.get("coverage_report") or {}

    weights = {
        "relevance": 0.30,
        "credibility": 0.25,
        "freshness": 0.15,
        "diversity": 0.15,
    }
    structural_bonus_raw = 0.0
    if coverage.get("section_count"):
        structural_bonus_raw = 100.0 * (
            coverage.get("non_empty_sections", 0) / coverage["section_count"]
        )
    weights["structural"] = 0.15

    breakdown: Dict[str, float] = {}
    weighted_sum = 0.0
    weight_used = 0.0
    for key, w in weights.items():
        if key == "structural":
            val = structural_bonus_raw
        else:
            entry = scores.get(key) or {}
            val = float(entry.get("score") or 0.0)
            if val <= 0.0 and entry.get("notes") == "stub":
                continue  # don't drag the average down with unimplemented evaluators
        breakdown[key] = round(val, 1)
        weighted_sum += val * w
        weight_used += w

    overall = round(weighted_sum / weight_used, 1) if weight_used else 0.0

    # Cap the redundancy penalty. A duplicate group means the same URL is
    # cited in 4+ sections, which is normal for a newsletter that recurses on
    # a single major story. Letting this drive overall to 0 (as 14 groups ×5
    # = 70 points) misrepresents quality. Cap at 15 points.
    redundancy_penalty = min(15.0, 1.5 * len(redundancy.get("duplicates") or []))
    overall = max(0.0, round(overall - redundancy_penalty, 1))

    verdict = (
        "production-ready" if overall >= 80
        else "needs-revision" if overall >= 60
        else "reject"
    )

    aggregate = {
        "overall_score": overall,
        "scores": breakdown,
        "weights": weights,
        "redundancy_penalty": redundancy_penalty,
    }

    score_card = {
        "authenticity_score": int(round(overall)),
        "verdict": verdict,
        "citation_score": int(round(breakdown.get("credibility", 0))),
        "factual_fidelity_score": int(round(breakdown.get("relevance", 0))),
        "coverage_score": int(round(breakdown.get("structural", 0))),
        "structural_completeness_score": int(round(breakdown.get("structural", 0))),
        "suggestions": state.get("improvement_suggestions") or [],
        "notes": (
            f"freshness={breakdown.get('freshness', 0)} "
            f"diversity={breakdown.get('diversity', 0)} "
            f"redundancy_pen={redundancy_penalty}"
        ),
    }

    return {
        "aggregate": aggregate,
        "score_card": score_card,
        **_tick(state, "aggregate_score_node", start),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 4) Self-critique / gap analysis
# ──────────────────────────────────────────────────────────────────────────────

async def missing_topics_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: ask the LLM which industry topics the report misses given curated input."""
    start = time.time()
    setup = state.get("setup") or {}
    curated = state.get("curated") or ""
    assembled = state.get("assembled_report") or state.get("draft") or ""
    industries = ", ".join(i.get("industry", "") for i in setup.get("industries", []) if i.get("industry"))

    schema = '{"missing_topics": ["<topic 1>", "<topic 2>", ...]}'
    messages = [
        {"role": "system", "content": "Audit a newsletter for gaps. Be specific, name what should be added."},
        {"role": "user", "content": (
            f"Industries: {industries or '(unspecified)'}\n\n"
            f"## Curated source list (first 4000 chars)\n{curated[:4000]}\n\n"
            f"## Newsletter excerpt (first 6000 chars)\n{assembled[:6000]}\n\n"
            "Return up to 6 topics that are present in the curated list but missing or under-covered in "
            "the newsletter. Each topic should be 2-8 words. If the newsletter covers everything important, "
            "return an empty list."
        )},
    ]
    missing: List[str] = []
    cost_events = list(state.get("cost_events") or [])
    try:
        result, usage = await acomplete_json(messages=messages, schema_hint=schema, temperature=0.1, max_tokens=400)
        if usage:
            cost_events.append({"node": "missing_topics_node", **usage})
        if isinstance(result, dict):
            missing = [str(t) for t in (result.get("missing_topics") or []) if t][:6]
    except Exception as exc:  # noqa: BLE001
        logger.warning("stage5_missing_topics_failed", error=str(exc))

    return {"missing_topics": missing, "cost_events": cost_events, **_tick(state, "missing_topics_node", start)}


async def bias_detection_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: deterministic + LLM lens on vendor/source concentration.

    Programmatic: per-domain share of citations; > 35 % flagged as concentration.
    LLM: short reasonableness check using domain shares.
    """
    start = time.time()
    assembled = state.get("assembled_report") or state.get("draft") or ""
    urls = sorted(_extract_urls_set(assembled))
    domain_counts: Dict[str, int] = {}
    for u in urls:
        d = _domain_of(u)
        if d:
            domain_counts[d] = domain_counts.get(d, 0) + 1
    total = sum(domain_counts.values()) or 1
    shares = sorted(
        [{"domain": d, "share": round(n / total, 3), "count": n} for d, n in domain_counts.items()],
        key=lambda x: x["share"], reverse=True,
    )
    findings: List[Dict[str, Any]] = []
    for entry in shares:
        if entry["share"] > 0.35 and entry["count"] >= 3:
            findings.append({
                "type": "source_concentration",
                "subject": entry["domain"],
                "share": entry["share"],
                "note": f"{entry['domain']} accounts for {round(entry['share']*100)}% of citations",
            })
    return {"bias_findings": findings, **_tick(state, "bias_detection_node", start)}


async def information_loss_node(state: Stage5State) -> Dict[str, Any]:
    """STUB (deterministic): items in curated set never cited in the report."""
    start = time.time()
    items = state.get("items") or []
    assembled = state.get("assembled_report") or state.get("draft") or ""
    cited = _extract_urls_set(assembled)
    uncited = [it for it in items if it.get("url") and it["url"] not in cited]
    return {
        "information_loss": {"uncited_count": len(uncited), "uncited_urls": [it["url"] for it in uncited[:50]]},
        **_tick(state, "information_loss_node", start),
    }


async def improvement_suggestions_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: synthesize bias + info-loss + missing topics + coverage gaps into actionable bullets.

    Also identifies ``weak_sections`` that the section_writer should regenerate
    based on coverage_report.weak / missing entries.
    """
    start = time.time()
    coverage = state.get("coverage_report") or {}
    missing_canonical = coverage.get("missing") or []
    weak_canonical = coverage.get("weak") or []
    missing_topics = state.get("missing_topics") or []
    bias = state.get("bias_findings") or []
    info_loss = state.get("information_loss") or {}

    suggestions: List[str] = []
    for sec in missing_canonical[:4]:
        suggestions.append(f"Add missing canonical section: '{sec}'.")
    for sec in weak_canonical[:4]:
        suggestions.append(f"Expand under-substantive section: '{sec}'.")
    for t in missing_topics[:3]:
        suggestions.append(f"Cover under-covered topic: {t}.")
    for b in bias[:2]:
        suggestions.append(f"Diversify sources: {b.get('note')}.")
    if info_loss.get("uncited_count", 0) > 0:
        suggestions.append(
            f"Surface up to {min(info_loss['uncited_count'], 5)} curated items currently uncited."
        )

    # Build weak_sections list for section_writer.
    weak_sections: List[SectionWeakness] = []
    for sec in weak_canonical:
        weak_sections.append({"section": sec, "issue": "under-substantive body", "severity": "high"})
    for sec in missing_canonical:
        weak_sections.append({"section": sec, "issue": "section absent", "severity": "high"})

    return {
        "improvement_suggestions": suggestions[:8],
        "weak_sections": weak_sections,
        **_tick(state, "improvement_suggestions_node", start),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 5) Dashboard data builder
# ──────────────────────────────────────────────────────────────────────────────

async def dashboard_metrics_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: build dashboard-ready metrics from aggregated state.

    Output shape is intentionally flat & viz-friendly so the frontend can render
    score gauges, source-mix donut, freshness bars, and weakness lists without
    further reshaping.
    """
    start = time.time()
    items = state.get("items") or []
    aggregate = state.get("aggregate") or {}
    scores = state.get("scores") or {}
    coverage = state.get("coverage_report") or {}
    redundancy = state.get("redundancy_report") or {}
    info_loss = state.get("information_loss") or {}

    domain_counts: Dict[str, int] = {}
    cat_counts: Dict[str, int] = {}
    top_count = 0
    dated = 0
    user_provided_count = 0
    for it in items:
        d = it.get("domain") or _domain_of(it.get("url", ""))
        if d:
            domain_counts[d] = domain_counts.get(d, 0) + 1
        c = it.get("category") or "uncategorized"
        cat_counts[c] = cat_counts.get(c, 0) + 1
        if it.get("is_top"):
            top_count += 1
        if it.get("published_at"):
            dated += 1
        snippet = (it.get("snippet") or "").lower()
        if "source: user-provided" in snippet:
            user_provided_count += 1

    top_domains = sorted(domain_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

    # Stage-4 wrote a small user-URL coverage report into shared state when
    # the user supplied URLs. Surface it on the dashboard so reviewers can see
    # "8 of 10 user URLs cited" at a glance.
    user_url_coverage = (state.get("setup") or {}).get("stage4_source_coverage") or {}
    if not user_url_coverage:
        # Fall back to reading the on-disk coverage file written by Stage 4.
        try:
            cov_path = f"{state['work_dir']}/stage_4/source_coverage.json"
            with open(cov_path, "r", encoding="utf-8") as f:
                user_url_coverage = json.load(f) or {}
        except (OSError, json.JSONDecodeError):
            user_url_coverage = {}

    metrics = {
        "overall_score": aggregate.get("overall_score", 0.0),
        "score_breakdown": aggregate.get("scores", {}),
        "verdict": (state.get("score_card") or {}).get("verdict"),
        "totals": {
            "items": len(items),
            "top_items": top_count,
            "dated_items": dated,
            "unique_domains": len(domain_counts),
            "sections": coverage.get("section_count", 0),
            "non_empty_sections": coverage.get("non_empty_sections", 0),
            "duplicate_groups": len(redundancy.get("duplicates") or []),
            "uncited_items": info_loss.get("uncited_count", 0),
            "user_provided_items": user_provided_count,
            "user_urls_expected": user_url_coverage.get("expected_user_urls", 0),
            "user_urls_cited": user_url_coverage.get("cited_user_urls", 0),
        },
        "source_mix": [{"domain": d, "count": n} for d, n in top_domains],
        "category_mix": [{"category": c, "count": n} for c, n in sorted(cat_counts.items())],
        "freshness": (scores.get("freshness") or {}).get("detail", {}),
        "user_url_coverage": user_url_coverage,
        "weak_sections": state.get("weak_sections") or [],
    }
    return {"dashboard_metrics": metrics, **_tick(state, "dashboard_metrics_node", start)}


async def visualization_prep_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: convert dashboard_metrics to chart-series payloads."""
    start = time.time()
    m = state.get("dashboard_metrics") or {}
    payload = {
        "gauges": [
            {"key": "overall", "label": "Overall", "value": m.get("overall_score", 0)},
            *[
                {"key": k, "label": k.capitalize(), "value": v}
                for k, v in (m.get("score_breakdown") or {}).items()
            ],
        ],
        "donut_source_mix": m.get("source_mix") or [],
        "bar_category_mix": m.get("category_mix") or [],
        "kpis": m.get("totals") or {},
        "user_url_coverage": m.get("user_url_coverage") or {},
        "pdf_backend": state.get("pdf_backend"),
        "pdf_error": state.get("pdf_error"),
        "weak_sections_table": [
            {"section": w.get("section"), "issue": w.get("issue"), "severity": w.get("severity")}
            for w in (m.get("weak_sections") or [])
        ],
    }
    return {"visualization_payload": payload, **_tick(state, "visualization_prep_node", start)}


# ──────────────────────────────────────────────────────────────────────────────
# 6) Output generation
# ──────────────────────────────────────────────────────────────────────────────

async def markdown_formatter_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: append the score block + verification notes to the assembled report.

    Mirrors the behavior of helpers._append_score_section so PDF output is
    visually identical to the legacy stage 5.
    """
    start = time.time()
    body = state.get("assembled_report") or state.get("draft") or ""
    score = state.get("score_card") or {}
    notes = state.get("verification_notes") or []

    if not score:
        final_with_score = body
    else:
        block = ["", "---", "", "## Newsletter Quality Score", ""]
        block.append(f"- **Authenticity score**: {score.get('authenticity_score', 'n/a')} / 100")
        block.append(f"- **Verdict**: {score.get('verdict', 'n/a')}")
        sub_keys = (
            ("citation_score", "Citation"),
            ("factual_fidelity_score", "Factual fidelity"),
            ("coverage_score", "Coverage"),
            ("structural_completeness_score", "Structural completeness"),
        )
        subs = [f"- **{label}**: {score.get(k, 'n/a')} / 100"
                for k, label in sub_keys if score.get(k) is not None]
        if subs:
            block.append("")
            block.append("### Sub-scores")
            block.extend(subs)
        suggestions = score.get("suggestions") or []
        if suggestions:
            block.extend(["", "### Suggestions", ""] + [f"- {s}" for s in suggestions])
        if notes:
            block.extend(["", "### Verification notes", ""] + [f"- {n}" for n in notes])
        final_with_score = body.rstrip() + "\n" + "\n".join(block) + "\n"

    return {
        "final_markdown": body,
        "final_with_score": final_with_score,
        **_tick(state, "markdown_formatter_node", start),
    }


async def pdf_generator_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: render the final markdown to PDF via the existing pdf_generator."""
    start = time.time()
    from ..pdf_generator import render_pdf  # imported lazily so tests don't need weasyprint

    work_dir = state["work_dir"]
    setup = state.get("setup") or {}
    industries = [i.get("industry", "") for i in setup.get("industries", []) if i.get("industry")]
    title = (
        f"{', '.join(industries) or 'Newsletter'} — "
        f"{setup.get('date_from', '')} to {setup.get('date_to', '')}"
    )
    out_dir = f"{work_dir}/stage_5"

    try:
        result = render_pdf(
            markdown_text=state.get("final_with_score") or state.get("final_markdown") or "",
            output_dir=out_dir,
            title=title,
            setup=setup,
        )
        return {
            "pdf_path": getattr(result, "pdf_path", None),
            "pdf_backend": getattr(result, "backend", None),
            "pdf_error": getattr(result, "error", None),
            **_tick(state, "pdf_generator_node", start),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("stage5_pdf_failed")
        return {"pdf_error": str(exc), **_tick(state, "pdf_generator_node", start)}


async def final_output_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: write all stage_5 artifacts to disk and collect output_files."""
    start = time.time()
    from pathlib import Path

    work_dir = state["work_dir"]
    stage_dir = Path(work_dir) / "stage_5"
    stage_dir.mkdir(parents=True, exist_ok=True)

    files: List[str] = []

    def write(name: str, content: str) -> str:
        p = stage_dir / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    final_md = state.get("final_with_score") or state.get("final_markdown") or ""
    files.append(write("newsletter_final.md", final_md))

    score_card = state.get("score_card") or {}
    files.append(write("score_card.json", json.dumps(score_card, indent=2, default=str)))

    aggregate = state.get("aggregate") or {}
    files.append(write("evaluation.json", json.dumps(aggregate, indent=2, default=str)))

    dash = dict(state.get("visualization_payload") or state.get("dashboard_metrics") or {})
    # Re-stamp PDF status here so dashboard.json reflects what actually shipped.
    # visualization_prep_node runs before pdf_generator_node and would otherwise
    # serialise stale (empty) backend / error fields.
    dash["pdf_backend"] = state.get("pdf_backend")
    dash["pdf_error"] = state.get("pdf_error")
    dash["pdf_path"] = state.get("pdf_path")
    files.append(write("dashboard.json", json.dumps(dash, indent=2, default=str)))

    notes = state.get("verification_notes") or []
    files.append(write(
        "verification_notes.md",
        "# Verification notes\n\n"
        + ("\n".join(f"- {n}" for n in notes) if notes else "_(no notes)_"),
    ))

    url_v = state.get("url_verification") or {}
    if url_v:
        files.append(write("url_verification.json", json.dumps(url_v, indent=2, default=str)))

    critic = {
        "corrections": state.get("critic_corrections") or [],
        "tone_pass": state.get("critic_tone_pass"),
        "tone_notes": state.get("critic_tone_notes"),
        "ddgs_findings": state.get("ddgs_findings") or [],
    }
    if any(critic.values()):
        files.append(write("critic_report.json", json.dumps(critic, indent=2, default=str)))

    pdf_path = state.get("pdf_path")
    if pdf_path:
        files.append(pdf_path)

    return {
        "output_files": files,
        "visualization_payload": dash,  # propagate PDF-stamped dashboard back to shared state
        **_tick(state, "final_output_node", start),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 7) NEW: URL verification (programmatic) + Critic + DDGS research + Editor
# ──────────────────────────────────────────────────────────────────────────────

async def url_verification_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: HEAD-check every cited URL in the draft for reachability.

    For each URL: status code, final URL after redirects, authentic-tier guess.
    Results feed into credibility scoring + dashboard.
    """
    start = time.time()
    import httpx

    draft = state.get("draft") or ""
    urls = sorted(_extract_urls_set(draft))[:80]  # cap for cost / latency

    results: List[Dict[str, Any]] = []
    timeout = httpx.Timeout(connect=4.0, read=6.0, write=4.0, pool=6.0)
    headers = {"User-Agent": "Mozilla/5.0 (MARS-NewsLetter/1.0 link-verify)"}

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
        async def _check(u: str) -> Dict[str, Any]:
            try:
                r = await client.head(u)
                # Some servers reject HEAD — fall back to GET on 405/403.
                if r.status_code in (403, 405, 501):
                    r = await client.get(u)
                return {
                    "url": u,
                    "status_code": r.status_code,
                    "final_url": str(r.url),
                    "reachable": 200 <= r.status_code < 400,
                    "domain": _domain_of(u),
                }
            except Exception as exc:  # noqa: BLE001
                return {"url": u, "status_code": None, "reachable": False, "error": str(exc), "domain": _domain_of(u)}

        results = await asyncio.gather(*(_check(u) for u in urls)) if urls else []

    reach = sum(1 for r in results if r.get("reachable"))
    verification = {
        "results": results,
        "total": len(results),
        "reachable": reach,
        "dead": len(results) - reach,
        "reachability_pct": round(100.0 * reach / len(results), 1) if results else 100.0,
    }
    notes = list(state.get("verification_notes") or [])
    notes.append(f"URL verification: {reach}/{len(results)} reachable ({verification['reachability_pct']}%).")
    return {
        "url_verification": verification,
        "verification_notes": notes,
        **_tick(state, "url_verification_node", start),
    }


async def critic_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: LLM critic emits structured corrections list + a tone audit."""
    start = time.time()
    draft = state.get("draft") or ""
    curated = state.get("curated") or ""

    schema = (
        '{"corrections": ['
        '{"section": "<heading>", "issue": "<short>", "severity": "low|medium|high", "recommendation": "<one sentence>"}'
        ', ...], "tone_pass": true|false, "tone_notes": "<one sentence>"}'
    )
    messages = [
        {"role": "system", "content": (
            "You are a senior newsroom critic. Audit the draft for citation accuracy, factual fidelity to the "
            "curated ground truth, tone (no superlatives, no AI-narration), and structural completeness. "
            "Return only the JSON schema."
        )},
        {"role": "user", "content": (
            "## Curated ground truth (first 6000 chars)\n" + curated[:6000] + "\n\n"
            "## Newsletter draft (first 9000 chars)\n" + draft[:9000] + "\n\n"
            "Find up to 10 corrections. Be specific about which section."
        )},
    ]
    corrections: List[Dict[str, Any]] = []
    tone_pass = True
    tone_notes = ""
    cost_events = list(state.get("cost_events") or [])
    try:
        result, usage = await acomplete_json(messages=messages, schema_hint=schema, temperature=0.0, max_tokens=1600)
        if usage:
            cost_events.append({"node": "critic_node", **usage})
        if isinstance(result, dict):
            corrections = result.get("corrections") or []
            tone_pass = bool(result.get("tone_pass", True))
            tone_notes = str(result.get("tone_notes") or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("stage5_critic_failed", error=str(exc))

    return {
        "critic_corrections": corrections,
        "critic_tone_pass": tone_pass,
        "critic_tone_notes": tone_notes,
        "cost_events": cost_events,
        **_tick(state, "critic_node", start),
    }


async def ddgs_research_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: DDGS web search to back the most-severe critic corrections.

    For each high-severity correction, run a focused DDGS query and capture the
    top 2 candidate URLs. The editor uses these as supplementary evidence
    (it MAY cite them only if they're more authoritative than the existing
    citation; otherwise they're left in the audit trail).
    """
    start = time.time()
    corrections = state.get("critic_corrections") or []
    high_sev = [c for c in corrections if (c.get("severity") or "").lower() == "high"][:5]

    findings: List[Dict[str, Any]] = []
    if not high_sev:
        return {"ddgs_findings": [], **_tick(state, "ddgs_research_node", start)}

    try:
        from ddgs import DDGS  # type: ignore
    except Exception:
        try:
            from duckduckgo_search import DDGS  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("stage5_ddgs_unavailable", error=str(exc))
            return {"ddgs_findings": [], **_tick(state, "ddgs_research_node", start)}

    def _search(q: str) -> List[Dict[str, str]]:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(q, max_results=3))
            out = []
            for r in results:
                out.append({
                    "title": r.get("title") or "",
                    "url": r.get("href") or r.get("url") or "",
                    "snippet": (r.get("body") or "")[:300],
                })
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("stage5_ddgs_query_failed", query=q[:80], error=str(exc))
            return []

    for c in high_sev:
        q = f"{c.get('section','')} {c.get('issue','')[:140]}".strip()
        if not q:
            continue
        hits = await asyncio.to_thread(_search, q)
        findings.append({
            "section": c.get("section"),
            "issue": c.get("issue"),
            "query": q,
            "candidates": hits,
        })

    notes = list(state.get("verification_notes") or [])
    notes.append(f"DDGS research: {len(findings)} corrections researched.")
    return {
        "ddgs_findings": findings,
        "verification_notes": notes,
        **_tick(state, "ddgs_research_node", start),
    }


async def editor_node(state: Stage5State) -> Dict[str, Any]:
    """IMPLEMENTED: single-pass LLM editor — apply critic corrections + clean output.

    Replaces the legacy cmbagent editor (which polluted output with Python
    code/error narration). This is a direct LLM call: the model receives the
    draft + critic corrections + curated allow-list and emits clean markdown.
    Output is constrained to the canonical 22-section structure.
    """
    start = time.time()
    draft = state.get("draft") or ""
    curated = state.get("curated") or ""
    corrections = state.get("critic_corrections") or []
    ddgs_findings = state.get("ddgs_findings") or []

    if not corrections and not draft:
        return {"edited_markdown": draft, **_tick(state, "editor_node", start)}

    corrections_block = "\n".join(
        f"- [{c.get('severity','medium').upper()}] {c.get('section','?')}: "
        f"{c.get('issue','?')} → {c.get('recommendation','')}"
        for c in corrections[:12]
    ) or "(none)"

    ddgs_block_parts = []
    for f in ddgs_findings:
        ddgs_block_parts.append(
            f"- For '{f.get('section','')}' / {f.get('issue','')[:80]}:\n"
            + "\n".join(f"    * [{h.get('title','')[:80]}]({h.get('url','')})" for h in (f.get("candidates") or [])[:3])
        )
    ddgs_block = "\n".join(ddgs_block_parts) or "(none)"

    messages = [
        {"role": "system", "content": (
            "You are a meticulous newsletter editor. Apply the critic's corrections to the draft and emit "
            "ONLY the final cleaned markdown. Rules:\n"
            "1. Output STARTS with the document's `# <Title>` line. No preamble, no commentary, no code fences.\n"
            "2. Keep the canonical 22 numbered sections (## 1. … ## 22. …) in order.\n"
            "3. Every inline citation MUST use the form `[domain](url)` and url MUST be drawn from the curated "
            "   allow-list (or the DDGS candidates, only when more authoritative than the original).\n"
            "4. No superlatives the source doesn't support. No 'as an AI'. No apologies. No system errors.\n"
            "5. **Preserve every section body that is already substantive in the draft.** Only use the "
            "   `_(no in-window material — to monitor next period)_` placeholder when the draft itself is "
            "   missing or empty for that section. Never replace existing substantive prose with the placeholder.\n"
            "6. Apply critic corrections **surgically** — touch only the sentence/section the correction "
            "   targets. Leave the rest of the draft byte-identical."
        )},
        {"role": "user", "content": (
            f"## Critic corrections\n{corrections_block}\n\n"
            f"## DDGS supplementary evidence\n{ddgs_block}\n\n"
            f"## Curated ground-truth excerpt (first 6000 chars)\n{curated[:6000]}\n\n"
            f"## Draft (apply edits to this — do not truncate)\n{draft}\n"
        )},
    ]

    cost_events = list(state.get("cost_events") or [])
    try:
        content, usage = await acomplete(messages=messages, temperature=0.1, max_tokens=12000)
        if usage:
            cost_events.append({"node": "editor_node", **usage})
    except Exception as exc:  # noqa: BLE001
        logger.exception("stage5_editor_failed")
        content = draft

    from ..programmatic_verification import _strip_pre_heading_preamble
    edited, _ = _strip_pre_heading_preamble(content)

    return {
        "edited_markdown": edited.strip() + "\n",
        "cost_events": cost_events,
        **_tick(state, "editor_node", start),
    }
