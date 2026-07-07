"""Stage runners for the 5-stage NewsLetter pipeline (production-grade).

Pipeline shape
--------------

::

    Stage 1  Setup            deterministic — persists user input, writes setup.md
       ↓
    Stage 2  Source Collection  cmbagent (planning+control): top companies →
                                per-company DDGS/DDGS queries → industry-wide
                                DDGS → dedupe + LinkValidator → raw_sources.md
       ↓
    Stage 3  Curation           cmbagent researcher — turns the raw dump into
                                a ranked, deduped, tagged curated.md, then
                                HEAD-verifies every URL and strips dead ones
       ↓
    Stage 4  Generation         stage4/runner.run_stage_4_sectioned — analyst
                                writes the outline, then a per-section writer
                                emits each of the 22 canonical sections in its
                                own small LLM call (avoids output-token clip)
       ↓
    Stage 5  Review             stage5/graph.run_stage_5_langgraph — a 22-node
                                LangGraph (URL verify → LLM critic → DDGS
                                claim re-check → editor → coverage → scorer →
                                PDF) plus a deterministic ``verify_and_clean``
                                safety net

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
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.logging import get_logger
from models.newsletter_schemas import CmbAgentMode, SourceMode

from .antirefusal import call_llm_with_antirefusal, is_refusal_text, rescue_seed
from .curated_quality_filter import apply_quality_filter
from .link_validator import LinkResult
from .mode_dispatcher import run_ai_stage
from .prompts.stages import curation_prompt
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
# P&C plan-shape guardrails
# ──────────────────────────────────────────────────────────────────────────────
#
# Stages 3, 4-analyst and 5 are content-*transformation* tasks: the researcher
# is given a source document and produces a structured markdown artefact from
# it. There is no ideation involved. Empirically, however, cmbagent's LLM
# planner treats "curate this list into markdown" as a research task and
# builds a multi-step plan that fans out to ``idea_maker`` and ``idea_hater``
# — those agents brainstorm about how to curate rather than actually running
# the researcher on the source document. The result is a 653 KB console log,
# zero researcher output, and an empty / hallucinated ``curated.md``.
#
# We prevent this at the planner boundary by:
#   1. Pinning the plan to a single step via ``max_plan_steps=1``.
#   2. Sending explicit ``plan_instructions`` that tell the planner it may
#      only use the researcher agent for this task.
#
# Both knobs are supported by ``mode_dispatcher._run_planning_control``.

_RESEARCHER_ONLY_PLAN_INSTRUCTIONS = (
    "This task is a pure content-transformation task, NOT an ideation or "
    "research-planning task. The plan MUST contain exactly ONE step, and that "
    "step MUST call the `researcher` agent. Do NOT include the `idea_maker`, "
    "`idea_hater`, or `engineer` agents in the plan. The researcher already "
    "has the source document embedded in the task prompt — its job is to "
    "transform that source document into the structured markdown output "
    "described in the task."
)


def _pin_single_step_researcher(merged: Dict[str, Any]) -> Dict[str, Any]:
    """Force a single-step researcher-only plan for content-transformation stages.

    Overrides ``max_plan_steps`` to 1 (and other planning knobs to their
    minimum values) so the P&C planner cannot fan out to idea_maker / idea_hater
    even if the planner LLM tries.
    """
    out = dict(merged or {})
    out.setdefault("max_plan_steps", 1)
    out.setdefault("n_plan_reviews", 0)
    # Give the single researcher step plenty of rounds to finish.
    out.setdefault("max_rounds_control", 20)
    return out


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
    merged = _pin_single_step_researcher(merged)

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
                plan_instructions=_RESEARCHER_ONLY_PLAN_INSTRUCTIONS,
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

    # Pre-verify every URL in the curated set so Stage 4 can never cite a
    # hallucinated URL. The curator can invent URLs that follow real
    # patterns (``ai.googleblog.com/...``) but don't actually resolve —
    # those propagate to the final report and show up as "dead" in the
    # dashboard. Catching them here lets the writer work from a clean
    # allow-list. ``tier=dead`` and ``tier=error`` URLs are stripped from
    # the curated markdown (the visible text stays). ``tier=blocked`` URLs
    # (live but CDN-anti-bot) are preserved.
    curated, stage3_url_health = await _verify_curated_urls(curated)

    # Deterministic quality filter: enforce strict date window + authority-
    # domain preference. The LLM curator can leave stale (2024-dated) items
    # in the set or list a low-authority third-party as `Primary source`
    # even when a vendor-official URL is present in `Also covered by`.
    # This filter drops out-of-window items and swaps Primary/Also links so
    # the canonical vendor URL always wins. See ``curated_quality_filter``.
    curated, quality_report = apply_quality_filter(
        curated,
        date_from=setup["date_from"],
        date_to=setup["date_to"],
    )

    path = _write(work_dir, 3, stage_def(3)["file"], curated)
    files = [path]
    quality_path = _write(
        work_dir, 3, "quality_filter.json", _json_dump(quality_report),
    )
    files.append(quality_path)
    logger.info(
        "stage_3_quality_filter",
        kept=quality_report.get("kept"),
        dropped=quality_report.get("dropped"),
        swaps=quality_report.get("swaps"),
    )
    if stage3_url_health.get("total"):
        validation_path = _write(
            work_dir, 3, "url_validation.json", _json_dump(stage3_url_health),
        )
        files.append(validation_path)
        logger.info(
            "stage_3_url_verification",
            total=stage3_url_health.get("total"),
            reachable=stage3_url_health.get("reachable"),
            stripped=stage3_url_health.get("stripped"),
        )

    return (
        {
            "curated": curated,
            "stage3_url_health": stage3_url_health,
            "stage3_quality_filter": quality_report,
        },
        curated,
        files,
    )


async def _verify_curated_urls(curated_md: str) -> Tuple[str, Dict[str, Any]]:
    """HEAD-/GET-check every URL in the curated markdown and strip dead ones.

    Returns ``(cleaned_curated_md, health_summary)``. The summary contains
    per-URL results plus aggregates and the count of URLs we removed. The
    markdown stripping keeps visible link text (``[text](dead-url)`` →
    ``text``) so the curator's prose remains readable, just unlinked.
    """
    import re as _re
    from .url_health import check_urls, summarise

    urls = sorted({
        u.rstrip(".,;:!?'\"]>")
        for u in _re.findall(r"https?://[^\s)\"'<>]+", curated_md or "")
    })
    if not urls:
        return curated_md, {}

    results = await check_urls(urls)
    summary = summarise(results)

    # Identify URLs to strip (genuinely dead — 404/410 + other 4xx + DNS errors).
    dead_urls = {r["url"] for r in results if r.get("tier") in ("dead", "error")}
    if not dead_urls:
        summary["stripped"] = 0
        summary["stripped_urls"] = []
        return curated_md, summary

    def _strip_md_link(m: _re.Match) -> str:
        url = m.group(2).rstrip(".,;:!?'\"]>")
        if url in dead_urls:
            return m.group(1)  # keep visible text only
        return m.group(0)

    cleaned = _re.sub(
        r"\[([^\]\n]+)\]\((https?://[^)\s\n]+)\)",
        _strip_md_link,
        curated_md,
    )
    # Drop bare ``<https://...>`` references to dead URLs too.
    for d in dead_urls:
        cleaned = cleaned.replace(f"<{d}>", "")
    # Tidy up any trailing whitespace that link removal left behind.
    cleaned = _re.sub(r"[ \t]+\n", "\n", cleaned)

    summary["stripped"] = len(dead_urls)
    summary["stripped_urls"] = sorted(dead_urls)
    return cleaned, summary


# ──────────────────────────────────────────────────────────────────────────────
# Stage 4 — Generation (section-by-section writer, 22 canonical sections)
# ──────────────────────────────────────────────────────────────────────────────
#
# The implementation lives in ``stage4/runner.py``. The runner writes each
# canonical section in its own bounded LLM call, then splices them together —
# this avoids the "writer runs out of output tokens and drops mid-document
# sections" failure mode of the older monolithic prompt.

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
    from .stage4 import run_stage_4_sectioned
    return await run_stage_4_sectioned(
        work_dir=work_dir, setup=setup, curated=curated,
        seed_companies=seed_companies, mode_override=mode_override,
        config_overrides=config_overrides, cost_callback=cost_callback,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Stage 5 — Review (LangGraph pipeline: verify URLs → critic → editor → scorer → PDF)
# ──────────────────────────────────────────────────────────────────────────────
#
# The implementation lives in ``stage5/graph.py`` and its per-node code in
# ``stage5/nodes.py``. It runs a 22-node LangGraph DAG that verifies every
# URL, has the LLM critic re-check factual claims with DDGS, applies the
# editor's fixes, runs the deterministic ``verify_and_clean`` safety net,
# scores the newsletter, and renders the PDF.

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
    from .stage5 import run_stage_5_langgraph
    return await run_stage_5_langgraph(
        work_dir=work_dir, setup=setup, draft=draft, curated=curated,
        mode_override=mode_override, config_overrides=config_overrides,
        cost_callback=cost_callback,
    )


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
