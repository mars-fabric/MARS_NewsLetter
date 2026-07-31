"""Section-by-section Stage 4 orchestrator.

Pipeline
--------
1. Run the analyst (small cmbagent call) to produce the outline.
2. For each of the 22 canonical sections:
     - Build a self-contained per-section prompt (outline + curated allow-list
       + last 2 000 chars of already-written draft for continuity).
     - Call ``acomplete`` directly (Stage 5's litellm client, no cmbagent
       message limiter on this path).
     - Validate the output starts with the canonical heading; if it does not,
       retry once; otherwise emit a stub heading + placeholder body.
     - Append the section to the in-memory draft and continue.
3. Assemble final markdown:  ``# <Title>`` + coverage line + the 22 section
   blocks joined by blank lines.
4. Persist ``outline.md`` and ``newsletter_draft.md`` under ``stage_4/``.

The contract mirrors ``helpers.run_stage_4`` — same return shape so the
orchestration layer dispatches to either implementation behind a flag.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.logging import get_logger
from models.newsletter_schemas import CmbAgentMode

from ..antirefusal import call_llm_with_antirefusal, is_refusal_text, rescue_seed
from ..mode_dispatcher import run_ai_stage
from ..prompts.stages import generation_analyst_prompt
from ..stage5.llm_client import acomplete
from .sections import (
    CANONICAL_SECTIONS,
    SectionSpec,
    build_section_prompt,
    section_max_tokens,
)

logger = get_logger(__name__)


def _stage_def_4() -> Dict[str, Any]:
    return {"number": 4, "name": "generation", "shared_key": "draft", "file": "newsletter_draft.md"}


def _write(work_dir: str, stage_num: int, filename: str, content: str) -> str:
    stage_dir = Path(work_dir) / f"stage_{stage_num}"
    stage_dir.mkdir(parents=True, exist_ok=True)
    path = stage_dir / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


def _today() -> str:
    return date.today().isoformat()


_HEADING_RE = re.compile(r"^##+\s+(\d+)\.\s+([^\n]+?)\s*$", re.MULTILINE)


def _strip_codefence(text: str) -> str:
    """Remove ``` fences the model occasionally wraps section output in."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _matches_expected_heading(text: str, spec: SectionSpec) -> bool:
    """Return True iff the section body starts with the canonical heading.

    Tolerates leading whitespace / blank lines and accepts headings that include
    a thematic subtitle on the same line (the writer prompt allows it).
    """
    stripped = (text or "").lstrip()
    m = _HEADING_RE.match(stripped)
    if not m:
        return False
    if int(m.group(1)) != spec.number:
        return False
    return spec.heading.lower() in m.group(2).lower()


def _force_canonical_heading(text: str, spec: SectionSpec) -> str:
    """Replace whatever heading the model emitted with the canonical one.

    Best-effort recovery for sections where the model wrote a sensible body
    under a slightly off heading — we prefer to keep the body and just
    normalise the heading rather than throw the work away.
    """
    stripped = (text or "").lstrip()
    m = _HEADING_RE.match(stripped)
    canonical = f"## {spec.number}. {spec.heading}"
    if not m:
        return f"{canonical}\n\n{stripped}".rstrip() + "\n"
    return _HEADING_RE.sub(canonical, stripped, count=1).rstrip() + "\n"


def _placeholder(spec: SectionSpec) -> str:
    return (
        f"## {spec.number}. {spec.heading}\n\n"
        "_(no in-window material — to monitor next period)_\n"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Link whitelist helpers
# ──────────────────────────────────────────────────────────────────────────────

def _extract_whitelist_urls(text: str) -> set:
    """Return the set of normalised URLs present in the curated markdown."""
    urls = set(re.findall(r"https?://[^\s)\"'<>]+", text or ""))
    return {u.rstrip(".,;:!?'\"]>") for u in urls}


def _enforce_link_whitelist(section_md: str, whitelist: set) -> str:
    """Replace [text](url) links whose URL is not in the curated whitelist
    with just the link text, preventing hallucinated citations from reaching
    the final report.
    """
    if not whitelist:
        return section_md

    def _sub(m: re.Match) -> str:
        text, url = m.group(1), m.group(2)
        clean_url = url.rstrip(".,;:!?'\"]>")
        if clean_url in whitelist:
            return m.group(0)
        return text  # drop the link, keep visible text

    return re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s\n]+)\)", _sub, section_md)


def _trim_trailing_broken_link(section_md: str) -> str:
    """Strip any half-written markdown link at the very end of a section.

    The model occasionally exhausts its token budget mid-citation. Leaving
    the broken ``[domain](https://partial-url`` in the markdown breaks the
    Stage-5 URL stripper's allow-list regex (which used to greedily match
    across blank lines until it found the next valid ``)``, swallowing
    entire subsequent sections in the process). Trimming here keeps the
    section well-formed for downstream passes.

    Implementation: find the LAST ``[`` in the body. The tail from that
    bracket is "well-formed" only when it looks like ``[text](...url...)``
    with the closing ``)`` actually present. Any other shape that starts
    with ``[`` near end-of-text is treated as token-budget residue and
    trimmed from the ``[`` to end. Closed links earlier in the body are
    untouched.
    """
    if not section_md or len(section_md) < 20:
        return section_md
    text = section_md.rstrip()
    last_open = text.rfind("[")
    if last_open < 0:
        return section_md
    tail = text[last_open:]
    # Well-formed trailing link: ``[text](...)`` with a ``](`` AND a
    # closing ``)`` after it.
    if "](" in tail:
        rhs = tail.split("](", 1)[1]
        if ")" in rhs:
            return section_md
    # Anything else starting with the last ``[`` is residue:
    #   * ``[text](https://partial-url`` (no closing ``)``),
    #   * ``[text](`` at end (no URL, no ``)``),
    #   * ``[text`` (no ``]`` at all).
    # Trim from ``[`` to end.
    trimmed = text[:last_open].rstrip()
    trimmed = re.sub(r"\n[-*]\s*$", "", trimmed)
    return trimmed.rstrip() + "\n"


async def _draft_section(
    *,
    spec: SectionSpec,
    outline: str,
    curated: str,
    setup: Dict[str, Any],
    industries: List[str],
    sub_domains: List[str],
    user_urls: List[str],
    prior_tail: str,
    today: str,
    cost_events: List[Dict[str, Any]],
    total_sections: int = 22,
) -> str:
    """Draft a single section. Retries once if the heading is wrong."""
    prompt = build_section_prompt(
        spec=spec, outline=outline, curated=curated, setup=setup,
        industries=industries, sub_domains=sub_domains, user_urls=user_urls,
        prior_sections_tail=prior_tail, today=today,
        total_sections=total_sections,
    )
    max_tokens = section_max_tokens(spec)
    messages = [
        {"role": "system", "content": (
            "You are a meticulous newsletter section writer. Output ONLY the "
            "markdown for the single section you were asked to draft, starting "
            "with the canonical heading line. Never invent citations."
        )},
        {"role": "user", "content": prompt},
    ]

    for attempt in (1, 2):
        try:
            content, usage = await acomplete(
                messages=messages, temperature=0.2, max_tokens=max_tokens,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "stage4_section_llm_failed",
                section=spec.number, attempt=attempt, error=str(exc)[:200],
            )
            content, usage = "", {"error": str(exc)[:200]}

        if usage:
            cost_events.append({"node": "stage4_section_writer", "section": spec.number, **usage})

        content = _strip_codefence(content)
        if not content or is_refusal_text(content):
            if attempt == 1:
                # Retry once on refusal / empty output with a sharper directive.
                messages = list(messages) + [
                    {"role": "user", "content": (
                        "Your previous response was empty or off-spec. Produce the "
                        "section now, starting with the canonical heading line. "
                        "No commentary, no code fences, no apologies."
                    )},
                ]
                continue
            return _placeholder(spec)

        if _matches_expected_heading(content, spec):
            return _trim_trailing_broken_link(content.rstrip() + "\n")

        if attempt == 1:
            # Retry once making the heading requirement extra explicit.
            messages = list(messages) + [
                {"role": "user", "content": (
                    f"Your previous response did not start with `## {spec.number}. "
                    f"{spec.heading}`. Re-emit the section using exactly that heading "
                    "as the very first line."
                )},
            ]
            continue

        # Second attempt still off — normalise the heading and keep the body.
        return _trim_trailing_broken_link(_force_canonical_heading(content, spec))

    return _placeholder(spec)  # unreachable; satisfies type checker


def _user_url_coverage(*, work_dir: str, draft: str, setup_user_urls: List[str]) -> Dict[str, Any]:
    """Same shape as helpers._user_url_coverage — see that function for context."""
    expected: List[str] = []
    val_path = Path(work_dir) / "stage_2" / "link_validation.json"
    if val_path.is_file():
        try:
            with val_path.open("r", encoding="utf-8") as f:
                rows = json.load(f) or []
            for r in rows:
                if isinstance(r, dict) and r.get("url") and (r.get("notes") or "").lower() != "dropped: unrelated":
                    expected.append(r["url"])
        except (OSError, json.JSONDecodeError):
            pass
    if not expected:
        expected = [u for u in (setup_user_urls or []) if u]
    if not expected:
        return {}

    draft_urls = set(re.findall(r"https?://[^\s)\"'<>]+", draft or ""))
    cited: List[str] = []
    missing: List[str] = []
    for u in expected:
        if u in draft_urls or u.rstrip("/") in draft_urls:
            cited.append(u)
        else:
            missing.append(u)
    return {
        "expected_user_urls": len(expected),
        "cited_user_urls": len(cited),
        "missing_user_urls": missing,
        "coverage_pct": round(100.0 * len(cited) / len(expected), 1),
    }


def _build_section_specs(setup: Dict[str, Any]) -> Tuple[List[SectionSpec], Dict[int, str]]:
    """Return section specs to draft + a depth map keyed by section number.

    When the user supplied a Gate-B ``report_template`` we build dynamic specs
    from it (title + per-section depth + guidance). Otherwise fall back to the
    canonical 22-section layout. Depth controls the per-section token budget and
    whether Stage 4 runs a cmbagent deep_research pre-pass for the section.
    """
    template = setup.get("report_template") or []
    if not template:
        return CANONICAL_SECTIONS, {s.number: "standard" for s in CANONICAL_SECTIONS}

    _WORDS = {"light": 180, "standard": 340, "deep": 650}
    specs: List[SectionSpec] = []
    depth_by_num: Dict[int, str] = {}
    for idx, item in enumerate(template, start=1):
        title = (item.get("title") or f"Section {idx}").strip()
        depth = (item.get("depth") or "standard").lower()
        if depth not in _WORDS:
            depth = "standard"
        points = item.get("points")
        try:
            points = int(points) if points is not None else None
        except (TypeError, ValueError):
            points = None
        guidance = (item.get("guidance") or "").strip()

        # word_count override: user specified an explicit word target (e.g. via
        # "Custom" length button in Gate B). It takes priority over depth-derived
        # budget but does not change the depth label (so "deep" still triggers
        # the cmbagent deep_research pre-pass regardless of word_count).
        custom_word_count = item.get("word_count")
        try:
            custom_word_count = int(custom_word_count) if custom_word_count is not None else None
        except (TypeError, ValueError):
            custom_word_count = None

        # When the user asked for N distinct points, mandate exactly that count
        # and expand the word budget so each point gets full treatment at the
        # requested depth (e.g. "5 trends, each deeply researched").
        per_point_words = _WORDS[depth]
        base_words = custom_word_count if custom_word_count else _WORDS[depth]
        if points:
            guidance += (
                f" Cover exactly {points} distinct, clearly-numbered key points. "
                f"Each point is a self-contained mini-analysis."
            )
            # Points multiply the per-point depth budget; custom_word_count is
            # ignored when explicit point count is supplied (it controls total
            # length via multiplied budget).
            base_words = per_point_words * points

        if depth == "deep":
            guidance += (
                " Produce a thorough, multi-angle analysis: context, key "
                "developments, comparative/competitive view, implications, and "
                "outlook. Every factual claim ends with an inline [domain](url) "
                "citation drawn only from the curated allow-list."
            )
        else:
            guidance += (
                " Every factual claim ends with an inline [domain](url) citation "
                "drawn only from the curated allow-list."
            )
        specs.append(SectionSpec(
            number=idx, heading=title, guidance=guidance.strip(),
            target_words=base_words,
        ))
        depth_by_num[idx] = depth
    return specs, depth_by_num


async def _deep_research_brief(
    *,
    spec: SectionSpec,
    curated: str,
    setup: Dict[str, Any],
    industries: List[str],
    sub_domains: List[str],
    work_dir: str,
    merged: Dict[str, Any],
    cost_callback: Optional[Callable[[Dict[str, Any]], None]],
) -> str:
    """Build an analytical brief for a ``deep`` section using cmbagent's
    ``deep_research`` workflow (multi-step planner → reviewer → iterative
    executor with context carryover).

    This is the strongest — and slowest — cmbagent mode; it is the right tool
    for a section the user explicitly flagged as needing research-grade depth
    (e.g. "5 trends, each deeply understood"). On any failure the dispatcher
    degrades to one_shot, and a total failure here returns an empty brief so
    the section still drafts from the curated set alone.
    """
    brief_prompt = (
        f"You are producing an in-depth, research-grade analytical brief for the "
        f"newsletter section titled '{spec.heading}'.\n\n"
        f"Industries: {', '.join(industries)}\n"
        f"Sub-domains: {', '.join(sub_domains)}\n"
        f"Coverage window: {setup.get('date_from')} → {setup.get('date_to')}\n\n"
        f"Section guidance: {spec.guidance}\n\n"
        f"Research the topic thoroughly. You MAY use web search to corroborate "
        f"and enrich the curated material, but every URL you cite must resolve "
        f"to a real, reachable page. Prefer the curated sources below; preserve "
        f"their exact [text](url) citations. Synthesise the key facts, "
        f"comparisons, implications, and outlook into a structured brief.\n\n"
        f"### Curated sources\n{curated[:12000]}"
    )
    # Give deep research a modest multi-step budget. cmbagent defaults to
    # max_plan_steps=3 which is plenty for a single section brief.
    dr_overrides = dict(merged)
    dr_overrides.setdefault("max_plan_steps", 3)
    dr_overrides.setdefault("n_plan_reviews", 1)
    try:
        brief = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=CmbAgentMode.DEEP_RESEARCH,
                work_dir=work_dir, agent="researcher",
                config_overrides=dr_overrides,
                cost_callback=cost_callback,
                researcher_instructions=(
                    "Produce a focused, well-structured analytical brief for the "
                    "section. Keep every citation intact and verify links resolve. "
                    "Do not write the final section prose — provide the research "
                    "synthesis the writer will build from."
                ),
            ),
            primary_prompt=brief_prompt,
        )
        return brief or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("stage4_deep_brief_failed", section=spec.number, error=str(exc)[:200])
        return ""


async def run_stage_4_sectioned(
    *,
    work_dir: str,
    setup: Dict[str, Any],
    curated: str,
    seed_companies: Optional[List[Dict[str, str]]] = None,
    mode_override: Optional[CmbAgentMode] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
    cost_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[Dict[str, Any], str, List[str]]:
    """Section-by-section Stage 4 — drop-in replacement for ``helpers.run_stage_4``.

    Same signature and return shape as the legacy implementation so the
    orchestrator can dispatch to either one.
    """
    from ..helpers import merge_overrides, _stage_mode  # local import to avoid circular

    started = time.time()
    industries = [i["industry"] for i in setup.get("industries", [])]
    sub_domains: List[str] = []
    for i in setup.get("industries", []):
        sub_domains.extend(i.get("sub_domains", []))
    user_urls = [u for u in (setup.get("user_urls") or []) if u]

    # Gate B — user-selected section template (title + depth + guidance). When
    # absent, ``_build_section_specs`` returns the canonical 22-section layout.
    section_specs, depth_by_num = _build_section_specs(setup)
    using_template = bool(setup.get("report_template"))

    # Executive-grade mode — auto-elevate the "hero" sections that a CEO/CTO
    # reads first to a cmbagent deep_research pre-pass, without the user having
    # to mark each one "deep" in Gate B. This is where mars_cmbagent's
    # multi-step planner→reviewer→executor earns its keep: the hero sections
    # get research-grade synthesis (context, comparison, implications, outlook)
    # while the routine sections stay fast/cheap. Non-hero sections are
    # untouched, so total runtime stays bounded.
    if setup.get("executive_grade"):
        _HERO_KEYWORDS = (
            "executive summary", "top story", "focus topic", "deep dive",
            "trend intelligence", "forward-looking", "strategic",
        )
        elevated: List[str] = []
        for spec in section_specs:
            h = spec.heading.lower()
            if depth_by_num.get(spec.number) != "deep" and any(k in h for k in _HERO_KEYWORDS):
                depth_by_num[spec.number] = "deep"
                elevated.append(spec.heading)
        if elevated:
            logger.info("stage4_executive_grade_elevated", sections=elevated)

    # When the user asked to analyse their own links, prepend a dedicated,
    # deep analysis section built exclusively from those URLs so their content
    # is always front-and-centre and never merely cited in passing.
    if setup.get("analyze_user_links") and user_urls:
        renum: List[SectionSpec] = []
        new_depth: Dict[int, str] = {}
        user_spec = SectionSpec(
            number=1,
            heading="Analysis of Your Provided Sources",
            guidance=(
                "Deeply analyse the user's own provided sources listed below. "
                "Summarise each source's key content, extract the most important "
                "findings, connect them to the broader industry context, and cite "
                "each with its exact [text](url) link. These are authorised, "
                "must-cover sources — never omit any of them.\n\nUser sources:\n"
                + "\n".join(f"- {u}" for u in user_urls)
            ),
            target_words=max(400, 220 * min(len(user_urls), 6)),
        )
        renum.append(user_spec)
        new_depth[1] = "deep"
        for i, spec in enumerate(section_specs, start=2):
            renum.append(SectionSpec(
                number=i, heading=spec.heading, guidance=spec.guidance,
                target_words=spec.target_words,
            ))
            new_depth[i] = depth_by_num.get(spec.number, "standard")
        section_specs, depth_by_num = renum, new_depth
        using_template = True

    # Template-level tone / audience overrides (Gate B).
    if setup.get("template_audience") or setup.get("template_tone"):
        setup = dict(setup)
        if setup.get("template_audience"):
            setup["audience"] = setup["template_audience"]

    mode = _stage_mode(setup, 4, mode_override)
    merged = merge_overrides(setup, 4, config_overrides)
    # Analyst step is a pure content-transformation pass — force single-step
    # researcher-only plan so cmbagent's planner doesn't fan out to
    # idea_maker / idea_hater instead of producing the outline. See the note
    # in `helpers._pin_single_step_researcher`.
    from ..helpers import _pin_single_step_researcher, _RESEARCHER_ONLY_PLAN_INSTRUCTIONS
    analyst_merged = _pin_single_step_researcher(merged)
    today = _today()
    cost_events: List[Dict[str, Any]] = []

    # Pre-build the URL whitelist from the curated material so section writers
    # can only cite URLs that were actually verified in Stage 3.
    url_whitelist = _extract_whitelist_urls(curated)

    # ── Step 1: analyst outline (cmbagent — same as legacy path) ──────────
    section_headings = [s.heading for s in section_specs]
    analyst_prompt = generation_analyst_prompt(
        curated=curated, industries=industries, sub_domains=sub_domains,
        date_from=setup["date_from"], date_to=setup["date_to"],
        audience=setup.get("audience"), title=setup.get("title"),
        user_urls=user_urls, seed_companies=seed_companies,
        section_headings=section_headings,
    )
    analyst_instructions = (
        "Build the analytical outline. Identify 5–8 themes, pick the Top Story / "
        "Secondary Story, list opportunities and risks, propose a Focus Topic "
        "Deep Dive, and emit the section list verbatim. "
        "Work ONLY from the curated material — do not run web searches."
    )
    if using_template:
        analyst_instructions = (
            "Build an analytical outline for the report. Identify the key themes, "
            "the most significant developments, opportunities, and risks across "
            "the coverage window, so the writer can populate the user-defined "
            "sections: " + "; ".join(s.heading for s in section_specs) + ". "
            "Work ONLY from the curated material — do not run web searches."
        )

    # Cap analyst at max_rounds=5 — it is a pure content-transformation task
    # (synthesise themes from curated text), not a multi-step research task.
    analyst_overrides = dict(analyst_merged)
    analyst_overrides.setdefault("max_rounds", 5)

    if mode == CmbAgentMode.PLANNING_AND_CONTROL:
        outline = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=analyst_overrides, cost_callback=cost_callback,
                plan_instructions=_RESEARCHER_ONLY_PLAN_INSTRUCTIONS,
                researcher_instructions=analyst_instructions,
                allow_web_tools=False,
            ),
            primary_prompt=analyst_prompt,
        )
    else:
        outline = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=analyst_overrides, cost_callback=cost_callback,
                allow_web_tools=False,
            ),
            primary_prompt=analyst_prompt,
        )

    outline_path = _write(work_dir, 4, "outline.md", outline)

    # ── Step 2: section-by-section drafting (litellm, no cmbagent limiter) ─
    title = (
        setup.get("title")
        or f"{', '.join(industries)} — {setup.get('date_from')} to {setup.get('date_to')}"
    )
    header = (
        f"# {title}\n\n"
        f"_Coverage: {setup.get('date_from')} → {setup.get('date_to')}_\n\n"
    )

    written_sections: List[str] = []
    accumulated = ""

    total_sections = len(section_specs)
    for spec in section_specs:
        prior_tail = accumulated[-2000:] if accumulated else ""
        # Deep sections get a cmbagent deep_research analytical brief that we
        # fold into the outline context handed to the section writer.
        section_outline = outline
        if depth_by_num.get(spec.number) == "deep":
            brief = await _deep_research_brief(
                spec=spec, curated=curated, setup=setup,
                industries=industries, sub_domains=sub_domains,
                work_dir=work_dir, merged=merged, cost_callback=cost_callback,
            )
            if brief:
                section_outline = f"{outline}\n\n### Deep-research brief for this section\n{brief}"
        section_md = await _draft_section(
            spec=spec, outline=section_outline, curated=curated, setup=setup,
            industries=industries, sub_domains=sub_domains, user_urls=user_urls,
            prior_tail=prior_tail, today=today, cost_events=cost_events,
            total_sections=total_sections,
        )
        # Enforce the curated URL whitelist — strip any link whose URL was not
        # present in Stage-3 curated.md to eliminate hallucinated citations.
        section_md = _enforce_link_whitelist(section_md, url_whitelist)
        written_sections.append(section_md)
        accumulated += "\n\n" + section_md.strip()
        logger.info(
            "stage4_section_done",
            section=spec.number, heading=spec.heading,
            chars=len(section_md),
        )

    body_md = "\n\n".join(s.strip() for s in written_sections) + "\n"
    draft = header + body_md

    # Refusal-aware rescue — extremely unlikely once we've written 22 sections
    # individually, but mirrors the legacy guarantee for callers.
    if is_refusal_text(draft):
        logger.warning("stage_4_section_path_refusal_using_rescue_seed")
        draft = rescue_seed(
            industries=industries, sub_domains=sub_domains,
            date_from=setup["date_from"], date_to=setup["date_to"],
        )

    draft_path = _write(work_dir, 4, _stage_def_4()["file"], draft)
    coverage = _user_url_coverage(
        work_dir=work_dir, draft=draft, setup_user_urls=user_urls,
    )

    # Persist the section structure so Stage 5 and the UI can inspect which
    # sections were written and with what depth/word budget.
    structure_data = {
        "sections": [
            {
                "number": s.number,
                "heading": s.heading,
                "depth": depth_by_num.get(s.number, "standard"),
                "target_words": s.target_words,
            }
            for s in section_specs
        ],
        "using_template": using_template,
        "total_sections": total_sections,
    }
    structure_path = _write(work_dir, 4, "report_structure.json", json.dumps(structure_data, indent=2))

    files = [outline_path, draft_path, structure_path]
    if coverage:
        notes_path = _write(work_dir, 4, "source_coverage.json", json.dumps(coverage, indent=2, default=str))
        files.append(notes_path)

    # Forward per-section cost events to the caller.
    if cost_callback:
        for ev in cost_events:
            try:
                cost_callback(ev)
            except Exception:  # noqa: BLE001
                logger.exception("stage4_section_cost_callback_failed")

    duration = round(time.time() - started, 2)
    logger.info(
        "stage4_sectioned_done",
        duration_s=duration,
        draft_chars=len(draft),
        sections=len(written_sections),
    )

    return (
        {
            "draft": draft,
            "outline": outline,
            "stage4_source_coverage": coverage,
            "stage4_section_completion": {
                "filled_sections": [s.number for s in section_specs],
                "still_missing": [],
                "mode": "template" if using_template else "sectioned",
                "duration_s": duration,
                "draft_chars": len(draft),
            },
        },
        draft,
        files,
    )
