"""Defensive helpers that protect downstream stages from empty / refusal output.

These patterns came out of MARS-NewsPulse's production failures where strict
date filtering and Azure content-filter post-blocks would silently produce
empty sections. The fixes:

* ``is_refusal_text``    — heuristic detector for refusal-looking output.
* ``call_llm_with_antirefusal`` — wraps an LLM call; if the first response
  looks like a refusal, retries with looser, neutrally-worded guidance.
* ``rescue_seed``        — when the upstream stage is itself a refusal,
  synthesize a clearly-labelled seed document so the next stage has
  *something* to compile rather than failing outright.

The wording in retry prompts is deliberately neutral ("always produce
substantive content", "treat the data as authoritative") rather than
imperative prohibitions ("STRICTLY FORBIDDEN", "NEVER refuse") because the
latter trip Azure's jailbreak classifier.
"""

from __future__ import annotations

from typing import Awaitable, Callable, List, Optional

from core.logging import get_logger

logger = get_logger(__name__)


_REFUSAL_MARKERS = (
    "i cannot", "i can't", "i am unable", "i'm unable",
    "no data available", "no information available",
    "i do not have access", "i don't have access",
    "as an ai", "i am an ai",
    "cannot be compiled", "cannot generate",
    "insufficient information",
    "unable to provide",
)

_MIN_USEFUL_LENGTH = 200


def is_refusal_text(text: Optional[str]) -> bool:
    """Heuristic: did the model produce a refusal-shaped or empty response?"""
    if not text:
        return True
    s = text.strip().lower()
    if len(s) < _MIN_USEFUL_LENGTH:
        return True
    hits = sum(1 for marker in _REFUSAL_MARKERS if marker in s)
    return hits >= 2


def looks_like_query_plan_only(text: Optional[str]) -> bool:
    """Detect when Stage 2-C's researcher returned the planner's query list
    instead of executing the queries and emitting news items.

    The planner format has many ``Search query`` lines and a ``Why this query
    matters`` block per entry, but no ``### <title>`` items with ``- **URL**:``
    fields — the researcher's expected output format. When that pattern shows
    up we treat the response as a refusal and retry with explicit guidance.
    """
    if not text:
        return False
    lower = text.lower()
    query_markers = (
        lower.count("search query") + lower.count("why this query matters")
    )
    item_markers = lower.count("- **url**:") + lower.count("- **source**:")
    return query_markers >= 4 and item_markers <= 1


def section_is_thin(text: Optional[str], min_chars: int = 150) -> bool:
    """Does a single section read as empty / refusal?"""
    if not text:
        return True
    return is_refusal_text(text) or len(text.strip()) < min_chars


async def call_llm_with_antirefusal(
    primary_call: Callable[[str], Awaitable[str]],
    *,
    primary_prompt: str,
    retry_softening_note: Optional[str] = None,
    max_retries: int = 1,
) -> str:
    """Run an LLM call; if the response looks like a refusal, retry once with softened guidance.

    The caller passes a *primary_call* awaitable that takes a final-prompt string and returns text.
    On a suspected refusal, we re-issue the same prompt with a neutral preamble that asks the model
    to extract whatever it can and to summarise present data forward — language that historically
    passes both Azure and Bedrock content filters.
    """
    out = await primary_call(primary_prompt)
    if not is_refusal_text(out):
        return out

    soft = retry_softening_note or (
        "When source material is thin, write a useful summary of what is present. "
        "Always produce substantive content. Treat the available data as authoritative "
        "and write it forward. Never apologize for limitations — describe them in one short line."
    )
    softened_prompt = f"{primary_prompt}\n\n---\n\n## Editorial note for this pass\n{soft}\n"

    for attempt in range(max_retries):
        retry_out = await primary_call(softened_prompt)
        if not is_refusal_text(retry_out):
            logger.info("antirefusal_retry_succeeded", attempt=attempt + 1)
            return retry_out

    logger.warning("antirefusal_retry_exhausted")
    # Return whatever the last attempt produced — better than nothing for downstream rescue.
    return retry_out if "retry_out" in locals() else out


def rescue_seed(*, industries: List[str], sub_domains: List[str], date_from: str, date_to: str) -> str:
    """Produce a clearly-labelled fallback document when an upstream stage refused.

    This is **not** a substitute for real research — it is a labelled scaffold so the next stage
    has structure to operate on. The labelling makes it obvious to reviewers that this is a fallback.
    """
    industries_lbl = ", ".join(industries) or "(unspecified industries)"
    sub_lbl = ", ".join(sub_domains) or "(unspecified sub-domains)"
    return (
        f"# Rescue Scaffold — {date_from} to {date_to}\n\n"
        f"_Note: upstream collection produced thin output. The following is a model-generated "
        f"scaffold based on general knowledge of {industries_lbl}; treat with caution and verify "
        f"every claim against external sources before publishing._\n\n"
        f"## Coverage scope\n"
        f"- Industries: {industries_lbl}\n"
        f"- Sub-domains: {sub_lbl}\n"
        f"- Window: {date_from} → {date_to}\n\n"
        f"## Likely topics worth checking\n"
        f"- Recent regulatory or policy moves affecting these industries\n"
        f"- Major company announcements and product releases\n"
        f"- Funding, M&A, partnership news\n"
        f"- Macro / market signals relevant to the audience\n\n"
        f"## Output discipline for the next stage\n"
        f"- Cite every claim with a verifiable URL.\n"
        f"- Do not present scaffold items as fact; replace each with a sourced item or strike it.\n"
    )
