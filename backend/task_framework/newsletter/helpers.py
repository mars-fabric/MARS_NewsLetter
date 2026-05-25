"""Stage runners for the 5-stage NewsLetter pipeline (production-grade).

Each ``run_stage_N`` is a coroutine that:
  * reads ``shared_state`` from previously-completed stages
  * does its work (deterministic Python and/or LLM via mode_dispatcher)
  * writes its primary artifact under ``stage_N/`` in the work directory
  * returns ``(updated_shared_state, primary_text, list_of_output_files)``

Stages 2–5 honour the per-stage ``CmbAgentMode``, ``StageModelOverrides``, and
``StageIterationLimits`` chosen at Setup time, with optional per-call overrides
forwarded from the execute endpoint.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.logging import get_logger
from models.newsletter_schemas import CmbAgentMode, SourceMode

from .antirefusal import call_llm_with_antirefusal, is_refusal_text, rescue_seed
from .link_validator import LinkResult
from .mode_dispatcher import run_ai_stage
from .pdf_generator import render_pdf
from .programmatic_verification import parse_score_card, verify_and_clean
from .prompts.stages import (
    curation_prompt,
    generation_analyst_prompt,
    generation_writer_prompt,
    review_critic_prompt,
    review_editor_prompt,
    score_card_prompt,
)
from .source_collector import collect_sources

logger = get_logger(__name__)

# Stage definitions are the single source of truth for what runs and where its
# primary output lands in shared_state.
STAGE_DEFS: List[Dict[str, Any]] = [
    {"number": 1, "name": "setup",             "shared_key": "setup",       "file": "setup.md"},
    {"number": 2, "name": "source_collection", "shared_key": "raw_sources", "file": "raw_sources.md"},
    {"number": 3, "name": "curation",          "shared_key": "curated",     "file": "curated.md"},
    {"number": 4, "name": "generation",        "shared_key": "draft",       "file": "newsletter_draft.md"},
    {"number": 5, "name": "review",            "shared_key": "final",       "file": "newsletter_final.md"},
]


def stage_def(stage_num: int) -> Dict[str, Any]:
    return STAGE_DEFS[stage_num - 1]


def stage_model_overrides(setup: Dict[str, Any], stage_num: int) -> Dict[str, Any]:
    """Setup-time per-stage model overrides."""
    mc = (setup or {}).get("mode_config") or {}
    raw = mc.get(f"stage_{stage_num}_models") or {}
    return {k: v for k, v in raw.items() if v}


def stage_iteration_limits(setup: Dict[str, Any], stage_num: int) -> Dict[str, Any]:
    """Setup-time per-stage iteration limits (n_plan_reviews, max_plan_steps, ...)."""
    mc = (setup or {}).get("mode_config") or {}
    raw = mc.get(f"stage_{stage_num}_limits") or {}
    return {k: v for k, v in raw.items() if v is not None}


def merge_overrides(setup: Dict[str, Any], stage_num: int,
                    per_call: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge setup-time models + setup-time limits + per-call overrides.

    Per-call values win. The result is a single flat dict that mode_dispatcher
    splits back into model_overrides vs iteration_limits internally.
    """
    flat: Dict[str, Any] = {}
    flat.update(stage_model_overrides(setup, stage_num))
    flat.update(stage_iteration_limits(setup, stage_num))
    flat.update(per_call or {})
    return flat


def _stage_mode(setup: Dict[str, Any], stage_num: int,
                override: Optional[CmbAgentMode]) -> CmbAgentMode:
    if override is not None:
        return override
    raw = (setup.get("mode_config") or {}).get(f"stage_{stage_num}_mode")
    if not raw:
        return CmbAgentMode.PLANNING_AND_CONTROL
    return CmbAgentMode(raw)


def _write(work_dir: str, stage_num: int, filename: str, content: str) -> str:
    stage_dir = Path(work_dir) / f"stage_{stage_num}"
    stage_dir.mkdir(parents=True, exist_ok=True)
    path = stage_dir / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


# ──────────────────────────────────────────────────────────────────────────────
# Stage 1 — Setup (deterministic: persist user input, generate setup summary)
# ──────────────────────────────────────────────────────────────────────────────

async def run_stage_1(
    *,
    work_dir: str,
    setup_payload: Dict[str, Any],
) -> Tuple[Dict[str, Any], str, List[str]]:
    industries = setup_payload.get("industries", [])
    industry_lines: List[str] = []
    for entry in industries:
        ind = entry.get("industry", "?")
        subs = ", ".join(entry.get("sub_domains", []))
        industry_lines.append(f"- **{ind}** — {subs}")

    mc = setup_payload.get("mode_config", {}) or {}
    mode_lines: List[str] = []
    for n in (2, 3, 4, 5):
        mode_lines.append(f"- Stage {n}: `{mc.get(f'stage_{n}_mode', 'planning_and_control')}`")

    md = (
        f"# Newsletter Setup\n\n"
        f"- **Title**: {setup_payload.get('title') or '(untitled)'}\n"
        f"- **Coverage window**: {setup_payload.get('date_from')} → {setup_payload.get('date_to')}\n"
        f"- **Audience**: {setup_payload.get('audience') or '(unspecified)'}\n"
        f"- **Source mode**: {setup_payload.get('source_mode')}\n"
        f"- **User-supplied URLs**: {len(setup_payload.get('user_urls', []))}\n"
        f"- **Top companies count (Stage 2)**: {mc.get('stage_2_top_companies_count', 12)}\n"
        f"- **Min sources target (Stage 2)**: {mc.get('stage_2_min_sources', 30)}\n\n"
        f"## Industries & sub-domains\n"
        + "\n".join(industry_lines)
        + "\n\n## CmbAgent mode per stage\n"
        + "\n".join(mode_lines)
        + "\n"
    )

    path = _write(work_dir, 1, stage_def(1)["file"], md)
    shared = {"setup": setup_payload}
    return shared, md, [path]


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2 — Source Collection (top companies → per-company news → industry-wide)
# ──────────────────────────────────────────────────────────────────────────────

async def run_stage_2(
    *,
    work_dir: str,
    setup: Dict[str, Any],
    mode_override: Optional[CmbAgentMode] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
    cost_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[Dict[str, Any], str, List[str]]:
    industries_with_subs: List[Tuple[str, List[str]]] = [
        (i["industry"], i.get("sub_domains", []))
        for i in setup.get("industries", [])
    ]
    source_mode = SourceMode(setup.get("source_mode", SourceMode.COMBINED.value))
    mc = setup.get("mode_config", {}) or {}
    enrich_with_llm = bool(mc.get("stage_2_enrich_with_llm", True))
    top_n = int(mc.get("stage_2_top_companies_count", 12))
    min_sources = int(mc.get("stage_2_min_sources", 30))

    mode = _stage_mode(setup, 2, mode_override)
    merged = merge_overrides(setup, 2, config_overrides)

    raw_md, validation, seed_companies = await collect_sources(
        industries_with_subdomains=industries_with_subs,
        date_from=setup["date_from"],
        date_to=setup["date_to"],
        user_urls=setup.get("user_urls", []),
        source_mode=source_mode,
        audience=setup.get("audience"),
        work_dir=work_dir,
        enrich_with_llm=enrich_with_llm,
        config_overrides=merged,
        cost_callback=cost_callback,
        mode=mode,
        top_companies_count=top_n,
        min_sources=min_sources,
    )

    raw_path = _write(work_dir, 2, stage_def(2)["file"], raw_md)
    validation_path = _write(
        work_dir, 2, "link_validation.json",
        _json_dump([r.to_dict() for r in validation]),
    )
    companies_path = _write(
        work_dir, 2, "top_companies.json",
        _json_dump(seed_companies),
    )

    shared = {
        "raw_sources": raw_md,
        "link_validation": [r.to_dict() for r in validation],
        "top_companies": seed_companies,
    }
    return shared, raw_md, [raw_path, validation_path, companies_path]


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3 — Curation
# ──────────────────────────────────────────────────────────────────────────────

async def run_stage_3(
    *,
    work_dir: str,
    setup: Dict[str, Any],
    raw_sources: str,
    mode_override: Optional[CmbAgentMode] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
    cost_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[Dict[str, Any], str, List[str]]:
    industries = [i["industry"] for i in setup.get("industries", [])]
    sub_domains: List[str] = []
    for i in setup.get("industries", []):
        sub_domains.extend(i.get("sub_domains", []))

    mode = _stage_mode(setup, 3, mode_override)
    merged = merge_overrides(setup, 3, config_overrides)

    prompt = curation_prompt(
        raw_collection=raw_sources,
        industries=industries,
        sub_domains=sub_domains,
        date_from=setup["date_from"],
        date_to=setup["date_to"],
        audience=setup.get("audience"),
    )

    if mode == CmbAgentMode.PLANNING_AND_CONTROL:
        researcher_instructions = (
            "Curate the raw Stage-2 collection per the rules in the task. Deduplicate by story (not URL), "
            "keep volume (≥ 25 items if the raw set is rich), tag each item with Category and Top: yes/no, "
            "and end with Coverage Notes + Curation Stats."
        )
        curated = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=merged, cost_callback=cost_callback,
                researcher_instructions=researcher_instructions,
            ),
            primary_prompt=prompt,
        )
    else:
        curated = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=merged, cost_callback=cost_callback,
            ),
            primary_prompt=prompt,
        )

    if is_refusal_text(curated):
        logger.warning("stage_3_refusal_using_rescue_seed")
        curated = rescue_seed(
            industries=industries, sub_domains=sub_domains,
            date_from=setup["date_from"], date_to=setup["date_to"],
        )

    path = _write(work_dir, 3, stage_def(3)["file"], curated)
    return {"curated": curated}, curated, [path]


# ──────────────────────────────────────────────────────────────────────────────
# Stage 4 — Generation (analyst → writer, 22 top-level sections)
# ──────────────────────────────────────────────────────────────────────────────

async def run_stage_4(
    *,
    work_dir: str,
    setup: Dict[str, Any],
    curated: str,
    seed_companies: Optional[List[Dict[str, str]]] = None,
    mode_override: Optional[CmbAgentMode] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
    cost_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[Dict[str, Any], str, List[str]]:
    # Default to the section-by-section path (PaperPulse pattern) — produces
    # long, non-truncated drafts by writing each canonical section in its own
    # small LLM call. Set ``STAGE4_SECTION_MODE=0`` to fall back to the legacy
    # monolithic cmbagent draft.
    if os.environ.get("STAGE4_SECTION_MODE", "1") not in ("0", "false", "no"):
        from .stage4 import run_stage_4_sectioned
        return await run_stage_4_sectioned(
            work_dir=work_dir, setup=setup, curated=curated,
            seed_companies=seed_companies, mode_override=mode_override,
            config_overrides=config_overrides, cost_callback=cost_callback,
        )

    industries = [i["industry"] for i in setup.get("industries", [])]
    sub_domains: List[str] = []
    for i in setup.get("industries", []):
        sub_domains.extend(i.get("sub_domains", []))

    mode = _stage_mode(setup, 4, mode_override)
    merged = merge_overrides(setup, 4, config_overrides)

    analyst_prompt = generation_analyst_prompt(
        curated=curated, industries=industries, sub_domains=sub_domains,
        date_from=setup["date_from"], date_to=setup["date_to"],
        audience=setup.get("audience"),
        title=setup.get("title"),
        user_urls=setup.get("user_urls"),
        seed_companies=seed_companies,
    )

    if mode == CmbAgentMode.PLANNING_AND_CONTROL:
        analyst_instructions = (
            "Build the analytical outline. Identify 5–8 themes, pick the Top Story / Secondary Story, "
            "list opportunities and risks, propose a Focus Topic Deep Dive, and emit the 22-section "
            "ordered list verbatim."
        )
        outline = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=merged, cost_callback=cost_callback,
                researcher_instructions=analyst_instructions,
            ),
            primary_prompt=analyst_prompt,
        )
    else:
        outline = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=merged, cost_callback=cost_callback,
            ),
            primary_prompt=analyst_prompt,
        )

    outline_path = _write(work_dir, 4, "outline.md", outline)

    writer_prompt = generation_writer_prompt(
        outline=outline, curated=curated, industries=industries, sub_domains=sub_domains,
        date_from=setup["date_from"], date_to=setup["date_to"],
        audience=setup.get("audience"),
        title=setup.get("title"),
        user_urls=setup.get("user_urls"),
    )

    if mode == CmbAgentMode.PLANNING_AND_CONTROL:
        writer_instructions = (
            "Draft the FULL 22-section newsletter (≥ 3500 words). Render every section heading exactly as "
            "specified. Use only URLs from the curated set. Cite inline as [<domain>](<url>). When a "
            "section has no in-window material, write '(no in-window material — to monitor next period)' "
            "rather than omitting the heading."
        )
        draft = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=merged, cost_callback=cost_callback,
                researcher_instructions=writer_instructions,
            ),
            primary_prompt=writer_prompt,
        )
    else:
        draft = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=merged, cost_callback=cost_callback,
            ),
            primary_prompt=writer_prompt,
        )

    if is_refusal_text(draft):
        logger.warning("stage_4_refusal_using_rescue_seed")
        draft = rescue_seed(
            industries=industries, sub_domains=sub_domains,
            date_from=setup["date_from"], date_to=setup["date_to"],
        )

    # Production gate: the writer sometimes runs out of output budget and
    # silently drops mid-document sections (e.g. emits 1-9 then jumps to
    # 19-22). Detect missing canonical sections and fill them in a focused
    # continuation pass so Stage 5 never sees a half-written report.
    draft, completion_report = await _ensure_22_sections(
        draft=draft, outline=outline, curated=curated,
        setup=setup, work_dir=work_dir, mode=mode, merged=merged,
        cost_callback=cost_callback,
    )
    if completion_report.get("filled_sections"):
        logger.info(
            "stage_4_continuation_pass_applied",
            filled=completion_report["filled_sections"],
            still_missing=completion_report.get("still_missing") or [],
        )

    draft_path = _write(work_dir, 4, stage_def(4)["file"], draft)
    coverage = _user_url_coverage(work_dir=work_dir, draft=draft,
                                  setup_user_urls=setup.get("user_urls") or [])
    files = [outline_path, draft_path]
    if coverage:
        notes_path = _write(work_dir, 4, "source_coverage.json", _json_dump(coverage))
        files.append(notes_path)
    if completion_report.get("filled_sections") or completion_report.get("still_missing"):
        cont_path = _write(work_dir, 4, "section_completion.json",
                           _json_dump(completion_report))
        files.append(cont_path)
    return (
        {
            "draft": draft, "outline": outline,
            "stage4_source_coverage": coverage,
            "stage4_section_completion": completion_report,
        },
        draft, files,
    )


# Canonical 22 sections — must stay in sync with prompts/stages.py writer prompt
# AND with stage5/nodes.py _CANONICAL_22 (single source of truth would be nicer,
# but cross-package import here would create a circular dep).
_CANONICAL_22_HELPERS: Tuple[str, ...] = (
    "Newsletter Metadata", "Editor's Note", "Executive Summary",
    "TL;DR", "Industry & Subdomain Focus", "Top Story of the Period",
    "Secondary Major Story", "Other Notable Headlines", "Subdomain Highlights",
    "Releases & Announcements", "Trend Intelligence", "Audience-Centric Analysis",
    "Focus Topic Deep Dive", "Source-Driven Insights", "Data & Evidence",
    "Quotes & Opinions", "Tools & Resources", "Action & Utility",
    "Forward-Looking Intelligence", "Transparency & Methodology",
    "Compliance & Trust", "Closure",
)


def _present_canonical_sections(draft: str) -> List[int]:
    """Return the indices (1-based) of canonical sections found in the draft."""
    import re
    headings = re.findall(r"^##+\s+([^\n]+)$", draft or "", flags=re.MULTILINE)
    present: List[int] = []
    for idx, name in enumerate(_CANONICAL_22_HELPERS, start=1):
        if any(name.lower() in h.lower() for h in headings):
            present.append(idx)
    return present


async def _ensure_22_sections(
    *, draft: str, outline: str, curated: str,
    setup: Dict[str, Any], work_dir: str, mode: CmbAgentMode,
    merged: Dict[str, Any],
    cost_callback: Optional[Callable[[Dict[str, Any]], None]],
) -> Tuple[str, Dict[str, Any]]:
    """If the writer dropped sections, run a focused continuation pass.

    Produces ONLY the missing section bodies, then splices them back into
    the draft at the right insertion points. Caps at one continuation pass —
    if it still misses anything, we surface that to Stage 5 / the dashboard
    rather than looping.
    """
    present = _present_canonical_sections(draft)
    missing_idx = [i for i in range(1, 23) if i not in present]
    if not missing_idx:
        return draft, {"filled_sections": [], "still_missing": []}

    missing_names = [_CANONICAL_22_HELPERS[i - 1] for i in missing_idx]
    catalogue = "\n".join(
        f"  {i}. ## {i}. {_CANONICAL_22_HELPERS[i - 1]}"
        for i in missing_idx
    )
    prompt = (
        f"# Newsletter Continuation — fill missing sections only\n\n"
        f"Coverage window: {setup.get('date_from')} → {setup.get('date_to')}\n"
        f"Industries: {', '.join(i.get('industry','') for i in setup.get('industries', []))}\n"
        f"Audience: {setup.get('audience') or 'general business stakeholders'}\n\n"
        "The Stage-4 writer produced a draft that is missing the canonical "
        "sections listed below. Write **only** those sections, in order, with "
        "their exact `## N. <Heading>` lines verbatim. Each section body must "
        "be substantive (60–180 words). Cite inline as `[<domain>](<url>)` "
        "drawn ONLY from the curated set below. If a section has no in-window "
        "material, keep the heading and write "
        "`_(no in-window material — to monitor next period)_` as the body.\n\n"
        f"## Sections to write (in order)\n{catalogue}\n\n"
        "## Outline (for thematic continuity)\n"
        "<<OUTLINE_BEGIN>>\n" + (outline or "")[:6000] + "\n<<OUTLINE_END>>\n\n"
        "## Curated source material (allow-list)\n"
        "<<CURATED_BEGIN>>\n" + (curated or "")[:12000] + "\n<<CURATED_END>>\n\n"
        "## Existing draft tail (last 1500 chars, for stylistic continuity)\n"
        "<<DRAFT_TAIL>>\n" + (draft or "")[-1500:] + "\n<<DRAFT_TAIL_END>>\n\n"
        "Output ONLY the missing section markdown — start with `## "
        f"{missing_idx[0]}. {_CANONICAL_22_HELPERS[missing_idx[0]-1]}` and "
        "end after the last requested section. No preamble, no closing "
        "commentary, no triple backticks."
    )

    try:
        added = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=CmbAgentMode.ONE_SHOT, work_dir=work_dir,
                agent="researcher", config_overrides=merged,
                cost_callback=cost_callback, max_rounds=10,
            ),
            primary_prompt=prompt,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("stage_4_continuation_failed", error=str(exc)[:200])
        return draft, {"filled_sections": [], "still_missing": missing_idx,
                       "error": str(exc)[:200]}

    if is_refusal_text(added) or not (added or "").strip():
        return draft, {"filled_sections": [], "still_missing": missing_idx,
                       "error": "continuation pass refused or empty"}

    merged_draft = _splice_continuation(draft=draft, addition=added,
                                        missing_idx=missing_idx)
    new_present = _present_canonical_sections(merged_draft)
    still_missing = [i for i in missing_idx if i not in new_present]
    filled = [i for i in missing_idx if i in new_present]
    return merged_draft, {"filled_sections": filled,
                          "still_missing": still_missing}


def _splice_continuation(*, draft: str, addition: str, missing_idx: List[int]) -> str:
    """Insert the continuation block at the lowest missing-index position.

    For the typical failure (writer emits 1-9 then jumps to 19-22 and the
    missing block is 10-18 contiguously), this puts the continuation between
    section 9 and section 19. For non-contiguous gaps, the addition is still
    inserted at the first gap point — better than appending at the end since
    Stage 5's section parser walks top-to-bottom.
    """
    import re
    if not missing_idx:
        return draft + "\n\n" + addition.strip() + "\n"
    first_missing = missing_idx[0]
    # Insert before the heading that follows the first missing index, i.e. the
    # next present canonical section after the gap.
    next_present = next((i for i in range(first_missing + 1, 23)
                        if i in _present_canonical_sections(draft)), None)
    cleaned = addition.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    if next_present is None:
        return draft.rstrip() + "\n\n" + cleaned + "\n"
    # Find the heading line for the next-present canonical section.
    name = _CANONICAL_22_HELPERS[next_present - 1]
    pattern = re.compile(
        r"^##+\s+(?:" + re.escape(str(next_present)) + r"\.\s+)?[^\n]*"
        + re.escape(name) + r"[^\n]*$",
        flags=re.MULTILINE | re.IGNORECASE,
    )
    m = pattern.search(draft)
    if not m:
        return draft.rstrip() + "\n\n" + cleaned + "\n"
    return draft[:m.start()].rstrip() + "\n\n" + cleaned + "\n\n" + draft[m.start():]


def _user_url_coverage(*, work_dir: str, draft: str, setup_user_urls: List[str]) -> Dict[str, Any]:
    """Diagnose whether the Stage-4 writer cited the user-provided URLs.

    Reads ``stage_2/link_validation.json`` if present (so we honour the relevance
    gate's "dropped: unrelated" notes), falling back to the raw setup list.
    Returns a small structured report consumed by Stage 5 / the dashboard. Does
    not fail or rewrite the draft — bubbling the gap is enough.
    """
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

    draft_urls = _extract_urls(draft)
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


# ──────────────────────────────────────────────────────────────────────────────
# Stage 5 — Review (critic → editor → score card) + clean URL strip + PDF
# ──────────────────────────────────────────────────────────────────────────────

async def run_stage_5(
    *,
    work_dir: str,
    setup: Dict[str, Any],
    draft: str,
    curated: str,
    mode_override: Optional[CmbAgentMode] = None,
    config_overrides: Optional[Dict[str, Any]] = None,
    cost_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[Dict[str, Any], str, List[str]]:
    # Stage 5 runs through the LangGraph pipeline (URL verification + LLM
    # critic + DDGS-backed claim re-search + editor + scorer + dashboard).
    # Set STAGE5_LEGACY=1 to fall back to the cmbagent-based path below.
    if os.environ.get("STAGE5_LEGACY") not in ("1", "true", "yes"):
        from .stage5 import run_stage_5_langgraph
        return await run_stage_5_langgraph(
            work_dir=work_dir, setup=setup, draft=draft, curated=curated,
            mode_override=mode_override, config_overrides=config_overrides,
            cost_callback=cost_callback,
        )

    industries = [i["industry"] for i in setup.get("industries", [])]
    sub_domains: List[str] = []
    for i in setup.get("industries", []):
        sub_domains.extend(i.get("sub_domains", []))

    mode = _stage_mode(setup, 5, mode_override)
    merged = merge_overrides(setup, 5, config_overrides)

    # ── Critic ────────────────────────────────────────────────────────────────
    critic_prompt = review_critic_prompt(
        draft=draft, curated=curated,
        date_from=setup["date_from"], date_to=setup["date_to"],
    )
    if mode == CmbAgentMode.PLANNING_AND_CONTROL:
        critic_instructions = (
            "Audit the draft against the curated ground truth. Emit a numbered Corrections List "
            "(Where / What is wrong / Recommended fix) and end with `## Verdict: pass | needs-revision`."
        )
        corrections = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=merged, cost_callback=cost_callback,
                researcher_instructions=critic_instructions,
            ),
            primary_prompt=critic_prompt,
        )
    else:
        corrections = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=merged, cost_callback=cost_callback,
            ),
            primary_prompt=critic_prompt,
        )
    corrections_path = _write(work_dir, 5, "corrections.md", corrections)

    # ── Editor ────────────────────────────────────────────────────────────────
    editor_prompt = review_editor_prompt(
        draft=draft, corrections=corrections, curated=curated,
        date_from=setup["date_from"], date_to=setup["date_to"],
    )
    if mode == CmbAgentMode.PLANNING_AND_CONTROL:
        editor_instructions = (
            "Apply the critic's corrections surgically. Preserve the 22-section structure. "
            "Strip any URL not present in the curated set, keeping the visible text intact. "
            "Output the final newsletter as clean markdown, no commentary."
        )
        edited = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=merged, cost_callback=cost_callback,
                researcher_instructions=editor_instructions,
            ),
            primary_prompt=editor_prompt,
        )
    else:
        edited = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=merged, cost_callback=cost_callback,
            ),
            primary_prompt=editor_prompt,
        )

    # ── Programmatic verification (clean strip — no strikethrough) ───────────
    allowed_urls = _extract_urls(curated)
    final, notes = verify_and_clean(final_text=edited, allowed_urls=allowed_urls)
    if notes:
        logger.info("verification_notes_applied", count=len(notes))

    final_path = _write(work_dir, 5, stage_def(5)["file"], final)

    # ── Score card (authenticity / verdict / suggestions) ────────────────────
    score_prompt = score_card_prompt(
        final_text=final, curated=curated,
        date_from=setup["date_from"], date_to=setup["date_to"],
        industries=industries, sub_domains=sub_domains,
        audience=setup.get("audience"),
    )
    score_raw = await call_llm_with_antirefusal(
        lambda p: run_ai_stage(
            prompt=p, mode=CmbAgentMode.ONE_SHOT, work_dir=work_dir, agent="researcher",
            config_overrides=merged, cost_callback=cost_callback,
            max_rounds=10,
        ),
        primary_prompt=score_prompt,
    )
    score_card = parse_score_card(score_raw)
    score_path = _write(work_dir, 5, "score_card.json", _json_dump(score_card))

    # ── Append a human-readable score block to the final markdown so PDF carries it ──
    final_with_score = _append_score_section(final, score_card, notes)
    _write(work_dir, 5, stage_def(5)["file"], final_with_score)

    # ── PDF ──────────────────────────────────────────────────────────────────
    industry_titles = ", ".join(industries) or "Newsletter"
    title = f"{industry_titles} — {setup.get('date_from')} to {setup.get('date_to')}"
    pdf = render_pdf(markdown_text=final_with_score, output_dir=os.path.join(work_dir, "stage_5"), title=title, setup=setup)

    notes_path = _write(
        work_dir, 5, "verification_notes.md",
        "# Verification notes\n\n"
        + ("\n".join(f"- {n}" for n in notes) if notes else "_(no notes)_"),
    )

    files = [corrections_path, final_path, notes_path, score_path]
    if pdf.success and pdf.pdf_path:
        files.append(pdf.pdf_path)

    shared: Dict[str, Any] = {
        "final": final_with_score,
        "verification_notes": notes,
        "pdf_path": pdf.pdf_path,
        "pdf_backend": pdf.backend,
        "pdf_error": pdf.error,
        "score_card": score_card,
    }
    return shared, final_with_score, files


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────

def append_score_section(final_md: str, score: Dict[str, Any], notes: List[str]) -> str:
    """Public alias used by repair endpoints — same behaviour as the internal helper."""
    return _append_score_section(final_md, score, notes)


def strip_score_section(final_md: str) -> str:
    """Remove the trailing `---\\n## Newsletter Quality Score` block, if present.

    Used when re-parsing the score card on a final markdown that already had a
    (possibly stale) score block appended.
    """
    if not final_md:
        return final_md
    marker = "## Newsletter Quality Score"
    idx = final_md.rfind(marker)
    if idx == -1:
        return final_md
    head = final_md[:idx].rstrip()
    if head.endswith("---"):
        head = head[: -len("---")].rstrip()
    return head + "\n"


def strip_empty_stub_sections(final_md: str) -> tuple[str, int]:
    """Drop ``## <Name>`` blocks whose only body is the canonical no-material stub.

    Returns (cleaned_text, count_removed). Used for one-shot repairs of
    documents written before the verifier learned to skip stub-appending when
    the document was already structurally complete.
    """
    import re as _re
    if not final_md:
        return final_md, 0
    # Anchor each match to a heading at start-of-line, then a blank line and
    # the literal stub. Consume only the heading + blank + stub; leave the
    # following blank lines untouched so adjacent stubs match independently.
    # ``re.MULTILINE`` lets ``^`` anchor at every line boundary.
    pattern = _re.compile(
        r"^##+\s+[^\n]+\n+_\(no in-window material[^\n]*\)_[ \t]*\n",
        flags=_re.MULTILINE,
    )
    cleaned, count = pattern.subn("", final_md)
    # Collapse triple+ blank lines that the deletions may have left behind.
    cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, count


def _append_score_section(final_md: str, score: Dict[str, Any], notes: List[str]) -> str:
    """Append a human-readable score block + verification notes to the final markdown."""
    if not score:
        return final_md

    score_lines = [
        "",
        "---",
        "",
        "## Newsletter Quality Score",
        "",
        f"- **Authenticity score**: {score.get('authenticity_score', 'n/a')} / 100",
        f"- **Verdict**: {score.get('verdict', 'n/a')}",
    ]
    sub_keys = (
        ("citation_score", "Citation"),
        ("factual_fidelity_score", "Factual fidelity"),
        ("coverage_score", "Coverage"),
        ("structural_completeness_score", "Structural completeness"),
    )
    sub_lines = [f"- **{label}**: {score.get(key, 'n/a')} / 100"
                 for key, label in sub_keys if score.get(key) is not None]
    if sub_lines:
        score_lines.append("")
        score_lines.append("### Sub-scores")
        score_lines.extend(sub_lines)

    suggestions = score.get("suggestions") or []
    if suggestions:
        score_lines.extend(["", "### Suggestions", ""] + [f"- {s}" for s in suggestions])

    if notes:
        score_lines.extend(["", "### Verification notes", ""] + [f"- {n}" for n in notes])

    if score.get("notes"):
        score_lines.extend(["", "### Reviewer notes", "", str(score["notes"])])

    return final_md.rstrip() + "\n" + "\n".join(score_lines) + "\n"


def _extract_urls(text: str) -> set[str]:
    """Pull every http(s) URL out of ``text`` and normalize trailing noise."""
    import re
    urls = set(re.findall(r"https?://[^\s)\"'<>]+", text or ""))
    cleaned = set()
    for u in urls:
        cleaned.add(u.rstrip(".,;:!?'\"]>"))
    return cleaned


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)
