"""Canonical 22-section spec + per-section prompt builder.

Section *names* live in :mod:`..constants` (single source of truth). This
module owns the per-section drafting *guidance* — word budgets, sub-section
shape, citation rules — everything the Stage-4 writer needs but that is not
useful to Stage-5 verifiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from ..constants import CANONICAL_HEADINGS as _NAMES


@dataclass(frozen=True)
class SectionSpec:
    number: int
    heading: str            # canonical heading text after the number
    guidance: str           # what the writer should produce
    target_words: int       # rough word budget (used to tune max_tokens)


# Full-form heading for slot 4 — the writer emits "TL;DR — Key Takeaways" so
# the section spec uses that form. Verifiers substring-match against the
# shorter "TL;DR" name from ``constants`` and both forms satisfy the check.
_HEADING_OVERRIDES = {4: "TL;DR — Key Takeaways"}


def _heading(idx: int) -> str:
    return _HEADING_OVERRIDES.get(idx, _NAMES[idx - 1])


# Per-section drafting guidance (word budget + shape). Order MUST match
# constants.CANONICAL_HEADINGS position-for-position.
_GUIDANCE: List[tuple[str, int]] = [
    # 1 Newsletter Metadata
    (
        "Render metadata as a tight bullet list: Title, Subtitle, Edition (V1), "
        "Date Range, Publication Date (today), Audience. No citations needed.",
        80,
    ),
    # 2 Editor's Note
    (
        "Write a 4–6 sentence editorial framing for the period. Lead with what is "
        "most important this edition and why the audience should read on. Cite the "
        "single most representative source inline.",
        150,
    ),
    # 3 Executive Summary
    (
        "Write a 5–8 sentence prose synthesis (no bullets) covering the period's "
        "most important developments. Every factual claim is followed by an inline "
        "[domain](url) citation drawn from the curated allow-list.",
        220,
    ),
    # 4 TL;DR — Key Takeaways
    (
        "Emit 5–8 markdown bullets. Each bullet is one sentence, names a specific "
        "event/company, and ends with an inline [domain](url) citation.",
        180,
    ),
    # 5 Industry & Subdomain Focus
    (
        "One paragraph (3–5 sentences) stating exactly which industries and "
        "sub-domains this edition covers and what falls outside scope.",
        120,
    ),
    # 6 Top Story of the Period
    (
        "Sub-sections: **Summary** (3–5 sentences), **Why it matters** (3–5 "
        "sentences), **Source(s)** (bullet list with [domain](url) citations). "
        "Pick the single most significant story from the curated set.",
        320,
    ),
    # 7 Secondary Major Story
    (
        "Same shape as Top Story — Summary / Impact / Source(s). Pick the second "
        "most significant story from the curated set, distinct from the Top Story.",
        300,
    ),
    # 8 Other Notable Headlines
    (
        "Bulleted list of 6–12 headlines. Each bullet: one sentence, names the "
        "company/event, ends with an inline [domain](url) citation. Sort by "
        "Top: yes flags first, then combined Relevance/Authority/Freshness score.",
        320,
    ),
    # 9 Subdomain Highlights
    (
        "Three sub-sections (`### Highlight #1`, `### Highlight #2`, `### Highlight #3`). "
        "Each highlight has **Details** (2–4 sentences) and **Source** "
        "([domain](url)). Pick the most important development per sub-domain.",
        350,
    ),
    # 10 Releases & Announcements
    (
        "Three sub-sections — `### Product / Platform Releases`, "
        "`### Feature Updates`, `### Research / Whitepapers`. Each lists 2–5 "
        "bullets with inline citations.",
        320,
    ),
    # 11 Trend Intelligence
    (
        "Three sub-sections — `### Emerging Trends`, `### Declining or Saturating "
        "Trends`, `### Market or Ecosystem Signals`. Each lists 2–4 short paragraphs "
        "or bullets, citing sources inline.",
        320,
    ),
    # 12 Audience-Centric Analysis
    (
        "Three sub-sections — `### What This Means for <audience>`, "
        "`### Opportunities`, `### Risks & Challenges`. Each gives 3–5 implication-"
        "led bullets with inline citations.",
        320,
    ),
    # 13 Focus Topic Deep Dive
    (
        "Three sub-sections — `### Background & Context`, "
        "`### What Changed in This Date Range`, `### Implications`. This is the "
        "longest section in the newsletter (400–550 words). Pick the topic the "
        "analyst outline flagged for deep treatment.",
        500,
    ),
    # 14 Source-Driven Insights
    (
        "Three sub-sections — `### Insights from Web Search Sources`, "
        "`### Insights from User-Provided Links`, `### Cross-Source Comparison`. "
        "User-supplied URLs (if any) MUST appear inline as citations here.",
        320,
    ),
    # 15 Data & Evidence
    (
        "Two sub-sections — `### Key Data Points`, `### Statistics Snapshot`. "
        "Extract 4–8 concrete figures from the curated snippets (percentages, "
        "dollar amounts, model sizes, release counts, benchmark scores, adoption "
        "rates). Format each as `- **<figure>** — <one-sentence context> "
        "[domain](url)`. Never invent a number — if the curated set has fewer "
        "than 4 figures, list what is available and add one line noting the gap.",
        260,
    ),
    # 16 Quotes & Opinions
    (
        "Two sub-sections — `### Notable Quotes` and `### Expert Commentary "
        "Summary`. Each quote must be reported (not fabricated); if no direct "
        "quote is available in the curated snippets, paraphrase the analyst's "
        "position and cite the source.",
        220,
    ),
    # 17 Tools & Resources
    (
        "Three sub-sections — `### Tools Mentioned`, `### Recommended Reading`, "
        "`### Documentation & References`. Bullets with [domain](url) citations.",
        220,
    ),
    # 18 Action & Utility
    (
        "Three sub-sections — `### Recommended Actions`, "
        "`### Strategic Considerations`, `### Watchlist Items`. Each gives 3–5 "
        "concise bullets framed for the audience.",
        260,
    ),
    # 19 Forward-Looking Intelligence
    (
        "Two sub-sections — `### Signals for the Next Period` and "
        "`### Predictions`. Predictions must be marked as predictive and tied to "
        "specific signals in the curated set.",
        220,
    ),
    # 20 Transparency & Methodology
    (
        "Four sub-sections — `### Source Collection Method`, `### Source List`, "
        "`### Content Selection Criteria`, `### AI Generation Notes`. The Source "
        "List enumerates the top domains cited in this edition.",
        260,
    ),
    # 21 Compliance & Trust
    (
        "Two sub-sections — `### Bias & Limitations Disclosure` and `### Disclaimer`. "
        "Disclose any known bias in source mix (e.g. vendor blogs vs. independent "
        "press), and add a standard AI-newsletter disclaimer.",
        180,
    ),
    # 22 Closure
    (
        "Two sub-sections — `### Next Edition Preview` (what we will watch in the "
        "following period) and `### Newsletter Footer` (industry · sub-domain · "
        "date range · 'Generated by AI' · version).",
        150,
    ),
]

assert len(_GUIDANCE) == 22, "Guidance list must cover all 22 sections."

CANONICAL_SECTIONS: List[SectionSpec] = [
    SectionSpec(number=i, heading=_heading(i), guidance=g, target_words=w)
    for i, (g, w) in enumerate([g for g in _GUIDANCE], start=1)
]


def canonical_headings() -> List[str]:
    return [s.heading for s in CANONICAL_SECTIONS]


def section_max_tokens(spec: SectionSpec) -> int:
    """Convert target_words into a max_tokens budget with a safety margin.

    Rough heuristic: 1 word ≈ 1.4 tokens for English markdown with citations.
    Multi-bullet sections with 3+ inline citations per bullet inflate the
    real token count well past the naive word estimate — citations alone
    can take 30-40 tokens each. We allow 3x the target plus a 1000-token
    floor so even short sections have room for their citation footprint
    without running out mid-link (which produced the
    ``[domain](https://...`` truncation seen on the first long-form run).
    """
    return max(1200, int(spec.target_words * 1.4 * 3.0))


def build_section_prompt(
    *,
    spec: SectionSpec,
    outline: str,
    curated: str,
    setup: dict,
    industries: List[str],
    sub_domains: List[str],
    user_urls: Optional[Iterable[str]],
    prior_sections_tail: str,
    today: str,
) -> str:
    """Build the user prompt for a single section.

    The prompt is deliberately self-contained — no chained chat history — so
    each section call is independent and small. Prior-section context is
    summarised by ``prior_sections_tail`` (the last ~2000 chars of accumulated
    markdown) for stylistic / continuity reasons, not as content the section
    body should restate.
    """
    aud = setup.get("audience") or "general business / industry stakeholders"
    title = (
        setup.get("title")
        or f"{', '.join(industries)} — {setup.get('date_from')} to {setup.get('date_to')}"
    )
    user_url_lines = "\n".join(f"  - {u}" for u in (user_urls or [])) or "  (none)"

    return (
        f"# Newsletter section writer — section {spec.number} of 22\n\n"
        f"Today is **{today}**. You are drafting **one section** of a long-form "
        f"professional newsletter. The other 21 sections are being written "
        f"separately — do not produce them.\n\n"
        f"- Newsletter title: {title}\n"
        f"- Coverage window: {setup.get('date_from')} → {setup.get('date_to')}\n"
        f"- Industries: {', '.join(industries) or '(unspecified)'}\n"
        f"- Sub-domains: {', '.join(sub_domains) or '(unspecified)'}\n"
        f"- Audience: {aud}\n\n"
        f"## This section\n"
        f"- Number: **{spec.number}**\n"
        f"- Canonical heading (use verbatim): `## {spec.number}. {spec.heading}`\n"
        f"- Target length: ~{spec.target_words} words.\n"
        f"- Guidance: {spec.guidance}\n\n"
        "## Drafting rules\n"
        "- Start your output with the canonical heading line above — exact text "
        "after the number. No preamble, no commentary, no code fences.\n"
        "- Every factual claim is followed by an inline `[<domain>](<url>)` "
        "citation. Use ONLY URLs that appear in the curated allow-list below.\n"
        "- Never invent links, statistics, or quotes. If the curated set has no "
        "in-window material for this section, keep the heading and write "
        "`_(no in-window material — to monitor next period)_` as the body — "
        "this is the ONLY acceptable form of stub.\n"
        "- Tone: professional, neutral, authoritative, implication-led. No "
        "superlatives the source does not support. No 'as an AI'. No apologies.\n"
        "- Do not repeat content from prior sections (see tail below). Add new "
        "framing, new angles, new bullets — not paraphrases.\n\n"
        "## Analyst outline (for thematic continuity)\n"
        "<<OUTLINE_BEGIN>>\n"
        f"{outline}\n"
        "<<OUTLINE_END>>\n\n"
        "## Curated source material (URL allow-list — use ONLY these URLs)\n"
        "<<CURATED_BEGIN>>\n"
        f"{curated}\n"
        "<<CURATED_END>>\n\n"
        "## User-supplied URLs (must be cited in Source-Driven Insights / "
        "Insights from User-Provided Links if any)\n"
        f"{user_url_lines}\n\n"
        "## Tail of already-written draft (last ~2000 chars — for tone continuity "
        "only; do NOT restate)\n"
        "<<PRIOR_TAIL_BEGIN>>\n"
        f"{prior_sections_tail or '(this is the first section being written)'}\n"
        "<<PRIOR_TAIL_END>>\n\n"
        "Output: only the markdown for this single section, starting with the "
        f"`## {spec.number}. {spec.heading}` heading."
    )
