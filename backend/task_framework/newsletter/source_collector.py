"""Stage-2 source collection — production pipeline.

Three substeps run in order (driven by the chosen ``CmbAgentMode``):

  **2-A — Top companies discovery.** A planner+researcher pass identifies
  the top-N companies in the chosen industries / sub-domains by running
  ranked DDGS queries. Skipped when ``top_companies_count == 0``.

  **2-B — Per-company news extraction.** For each discovered company, run a
  ``site:<domain>`` search plus free-form coverage queries to extract recent
  news / innovations. The results are emitted as a markdown list grouped by
  company.

  **2-C — Industry-wide discovery.** A second planner+researcher pass that
  catches developments not tied to a specific company (regulatory action,
  cross-vendor benchmarks, market signals). The minimum-source mandate is
  enforced here so the curator has enough material for a long newsletter.

All three substeps merge user-supplied URLs into the planner's seed (so the
researcher cross-validates them via ``site:`` follow-ups) — that is the
"merged into the planner's seed" rule the user picked.

The function returns a single long markdown collection that the curator
(Stage 3) consumes directly, plus the structured link-validation report and
the parsed list of seed companies (used by the writer in Stage 4).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.logging import get_logger
from models.newsletter_schemas import CmbAgentMode, SourceMode

from .antirefusal import call_llm_with_antirefusal, looks_like_query_plan_only
from .link_validator import LinkResult, summarize_validation, validate_links
from .mode_dispatcher import run_ai_stage  # noqa: F401 — used by relevance gate via local import
from .prompts.stages import (
    discovery_planner_prompt,
    discovery_researcher_prompt,
    per_company_news_prompt,
    top_companies_planner_prompt,
    top_companies_researcher_prompt,
)

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Public entrypoint
# ──────────────────────────────────────────────────────────────────────────────

async def collect_sources(
    *,
    industries_with_subdomains: List[Tuple[str, List[str]]],
    date_from: str,
    date_to: str,
    user_urls: List[str],
    source_mode: SourceMode,
    audience: Optional[str],
    work_dir: str,
    enrich_with_llm: bool,
    config_overrides: Optional[Dict[str, Any]] = None,
    cost_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    mode: CmbAgentMode = CmbAgentMode.PLANNING_AND_CONTROL,
    top_companies_count: int = 12,
    min_sources: int = 30,
) -> Tuple[str, List[LinkResult], List[Dict[str, str]]]:
    industries = [i for i, _ in industries_with_subdomains]
    sub_domains: List[str] = []
    for _, subs in industries_with_subdomains:
        sub_domains.extend(subs)

    config_overrides = config_overrides or {}

    # ── 1. Validate user URLs (always when supplied unless mode is DDGS-only) ──
    validation: List[LinkResult] = []
    if user_urls and source_mode != SourceMode.DDGS_ONLY:
        validation = await validate_links(user_urls, industries=industries)
        # Soft relevance gate — only drop a user URL when the model explicitly
        # says it's unrelated to the industries. "unknown" / "borderline"
        # verdicts keep the link in the set; the user added it for a reason.
        validation = await _gate_user_urls_relevance(
            validation=validation, industries=industries, sub_domains=sub_domains,
            work_dir=work_dir, mode=mode, config_overrides=config_overrides,
            cost_callback=cost_callback,
        )
        logger.info(
            "user_urls_validated",
            total=len(validation),
            reachable=sum(1 for r in validation if r.reachable),
            authentic=sum(1 for r in validation if r.is_authentic),
            kept_after_relevance_gate=sum(1 for r in validation if (r.notes or "").lower() != "dropped: unrelated"),
        )

    sections: List[str] = [
        "# Stage 2 — Source Collection",
        "",
        f"_Coverage window: **{date_from} → {date_to}**_",
        f"_Source mode: **{source_mode.value}**_",
        f"_Pipeline mode: **{mode.value}**_",
        "",
    ]

    # ── 2. User URLs section (always rendered when we have them). The
    # relevance gate may have tagged some "dropped: unrelated"; we render
    # them but flag them visibly so the curator knows not to cite them.
    if validation:
        sections.append("## User-Provided Links — Validation")
        sections.append(summarize_validation(validation))
        sections.append("")

    # ── 3. User-only mode short-circuits the DDGS path. ──────────────────────
    if source_mode == SourceMode.USER_LINKS_ONLY:
        if enrich_with_llm and validation:
            enriched = await _enrich_user_urls(
                validation=validation, industries=industries, sub_domains=sub_domains,
                date_from=date_from, date_to=date_to, work_dir=work_dir,
                mode=mode, config_overrides=config_overrides, cost_callback=cost_callback,
            )
            sections.append("## Enriched User Items")
            sections.append(enriched)
            sections.append("")
        return "\n".join(sections), validation, []

    # ── 4. DDGS / combined path: 3 substeps. ──────────────────────────────────
    # Production rule: in DDGS/COMBINED modes we always discover the top-N
    # companies. Even a small floor of 6 is better than skipping company
    # discovery entirely, because the per-company news pass anchors Stage 3
    # with vendor-canonical sources. A caller can still pass top_n=0 to skip,
    # but the UI default is 10+.
    effective_top_n = max(int(top_companies_count or 0), 6)
    seed_companies: List[Dict[str, str]] = []
    company_md, seed_companies = await _discover_top_companies(
        industries=industries, sub_domains=sub_domains, top_n=effective_top_n,
        date_from=date_from, date_to=date_to,
        user_urls=user_urls if source_mode == SourceMode.COMBINED else [],
        audience=audience, work_dir=work_dir, mode=mode,
        config_overrides=config_overrides, cost_callback=cost_callback,
    )
    sections.append(f"## 2-A — Top {effective_top_n} Companies (web-discovered)")
    sections.append(company_md)
    sections.append("")

    if seed_companies:
        per_company_md = await _extract_per_company_news(
            companies=seed_companies, industries=industries, sub_domains=sub_domains,
            date_from=date_from, date_to=date_to, work_dir=work_dir, mode=mode,
            config_overrides=config_overrides, cost_callback=cost_callback,
        )
        sections.append("## 2-B — Per-Company News & Innovations")
        sections.append(per_company_md)
        sections.append("")

    # 2-C: industry-wide discovery (always runs when we're in DDGS / combined).
    industry_md = await _industry_wide_discovery(
        industries=industries, sub_domains=sub_domains,
        date_from=date_from, date_to=date_to,
        user_urls=user_urls if source_mode == SourceMode.COMBINED else [],
        source_mode=source_mode.value, audience=audience,
        seed_companies=seed_companies,
        min_sources=min_sources,
        work_dir=work_dir, mode=mode,
        config_overrides=config_overrides, cost_callback=cost_callback,
    )
    sections.append("## 2-C — Industry-Wide News & Trends")
    sections.append(industry_md)
    sections.append("")

    # 2-D: enrich user URLs as structured items in COMBINED mode so the
    # curator (Stage 3) sees them as first-class content, not just a
    # validation table. USER_LINKS_ONLY already short-circuits earlier.
    if source_mode == SourceMode.COMBINED and validation and enrich_with_llm:
        keep = [r for r in validation if (r.notes or "").lower() != "dropped: unrelated"]
        if keep:
            enriched = await _enrich_user_urls(
                validation=keep, industries=industries, sub_domains=sub_domains,
                date_from=date_from, date_to=date_to, work_dir=work_dir,
                mode=mode, config_overrides=config_overrides, cost_callback=cost_callback,
            )
            sections.append("## 2-D — User-Provided Links (enriched)")
            sections.append(enriched)
            sections.append("")

    return "\n".join(sections), validation, seed_companies


# ──────────────────────────────────────────────────────────────────────────────
# Substep 2-A: Top companies discovery
# ──────────────────────────────────────────────────────────────────────────────

async def _discover_top_companies(
    *, industries: List[str], sub_domains: List[str], top_n: int,
    date_from: str, date_to: str, user_urls: List[str], audience: Optional[str],
    work_dir: str, mode: CmbAgentMode,
    config_overrides: Dict[str, Any],
    cost_callback: Optional[Callable[[Dict[str, Any]], None]],
) -> Tuple[str, List[Dict[str, str]]]:
    """Run the 2-A pass and parse the resulting markdown into a structured company list."""
    plan = top_companies_planner_prompt(
        industries=industries, sub_domains=sub_domains, top_n=top_n,
        date_from=date_from, date_to=date_to, audience=audience, user_urls=user_urls,
    )
    research = top_companies_researcher_prompt(
        industries=industries, sub_domains=sub_domains, top_n=top_n,
        date_from=date_from, date_to=date_to, user_urls=user_urls,
    )

    # Always use ONE_SHOT for web-research substeps regardless of the user's stage
    # mode. Planning_and_control consistently times out or fails its control phase
    # on DDGS-heavy tasks (12 companies × 8 backends = 96+ HTTP calls), then the
    # mandatory fallback to one_shot consumes another 240s. Skipping straight to
    # one_shot saves the wasted P&C overhead and gives the researcher its full
    # time budget in a single pass.
    merged = (
        plan
        + "\n\n---\n\n"
        + research
        + "\n\n## Important — one_shot discipline\n"
        "- Plan your queries internally, then **execute** them and emit the final\n"
        "  numbered company list in the exact format described above.\n"
        "- Do NOT emit a list of planned search queries as the answer.\n"
        "- Call the duckduckgo_search TOOL (do not write Python code).\n"
    )
    researcher_md = await call_llm_with_antirefusal(
        lambda p: run_ai_stage(
            prompt=p, mode=CmbAgentMode.ONE_SHOT, work_dir=work_dir, agent="researcher",
            config_overrides=config_overrides, cost_callback=cost_callback,
        ),
        primary_prompt=merged,
    )

    companies = _parse_top_companies(researcher_md)
    logger.info("top_companies_parsed", requested=top_n, parsed=len(companies))
    if not companies:
        # An empty parse is not fatal — 2-C (industry-wide discovery) still
        # runs and produces the bulk of Stage 2 content. Per-company news
        # (2-B) simply gets skipped and the writer's Company Landscape
        # section is populated from curated items instead.
        logger.warning(
            "top_companies_parse_empty",
            requested=top_n,
            researcher_md_len=len(researcher_md or ""),
            hint="planner likely emitted idea_maker template output; 2-B will be skipped",
        )
    return researcher_md, companies


_COMPANY_LINE_RE = re.compile(
    r"^\s*\d+\.\s*\*\*([^*]+)\*\*\s*[—\-]\s*(?:<)?(https?://[^>\s]+)",
    re.MULTILINE,
)


def _parse_top_companies(md: str) -> List[Dict[str, str]]:
    """Extract the ``<n>. **<name>** — <https://domain>`` lines from 2-A output."""
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for m in _COMPANY_LINE_RE.finditer(md or ""):
        name = m.group(1).strip()
        url = m.group(2).strip().rstrip(".,;:!?'\"]>")
        domain = _domain_of(url)
        key = domain.lower() or name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "domain": domain, "url": url})
    return out


def _domain_of(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# Substep 2-B: Per-company news extraction
# ──────────────────────────────────────────────────────────────────────────────

async def _extract_per_company_news(
    *, companies: List[Dict[str, str]], industries: List[str], sub_domains: List[str],
    date_from: str, date_to: str, work_dir: str, mode: CmbAgentMode,
    config_overrides: Dict[str, Any],
    cost_callback: Optional[Callable[[Dict[str, Any]], None]],
) -> str:
    """Run the 2-B pass — one researcher pass for the full company set.

    We send the entire company list in a single prompt rather than looping per
    company because cmbagent's planning_and_control benefits from being able to
    plan across companies (e.g. identifying common themes, reusing search
    queries). The researcher emits one ``## <Company>`` section per company.
    """
    prompt = per_company_news_prompt(
        companies=companies, industries=industries, sub_domains=sub_domains,
        date_from=date_from, date_to=date_to,
    )

    # Always use ONE_SHOT for 2-B. P&C adds overhead (planning phase, control
    # loop) and consistently times out or routes to the engineer agent for
    # Python script generation instead of direct DDGS tool calls.
    one_shot_prompt = (
        prompt
        + "\n\n## Important — one_shot discipline\n"
        "- For each company, call the `duckduckgo_search` TOOL directly — do NOT write Python code.\n"
        "- Plan your queries internally, then execute them and emit the `## <Company>` sections.\n"
        "- Do NOT emit a list of planned search queries as the final answer.\n"
        "- Always include at least the most recent item per company from the snippet content.\n"
    )
    return await call_llm_with_antirefusal(
        lambda p: run_ai_stage(
            prompt=p, mode=CmbAgentMode.ONE_SHOT, work_dir=work_dir, agent="researcher",
            config_overrides=config_overrides, cost_callback=cost_callback,
        ),
        primary_prompt=one_shot_prompt,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Substep 2-C: Industry-wide discovery
# ──────────────────────────────────────────────────────────────────────────────

async def _industry_wide_discovery(
    *, industries: List[str], sub_domains: List[str],
    date_from: str, date_to: str, user_urls: List[str],
    source_mode: str, audience: Optional[str],
    seed_companies: List[Dict[str, str]],
    min_sources: int,
    work_dir: str, mode: CmbAgentMode,
    config_overrides: Dict[str, Any],
    cost_callback: Optional[Callable[[Dict[str, Any]], None]],
) -> str:
    """Industry-wide planner + researcher pass with a minimum-source mandate.

    Historical bug (fixed 2026-07-06): the P&C branch used to pass the entire
    ``discovery_planner_prompt`` string as ``plan_instructions``. That prompt
    is intended to be a *primary prompt* that produces a query list — when
    passed as ``plan_instructions`` the planner obeyed it literally and
    emitted the query list AS THE STAGE OUTPUT (30 numbered queries with
    rationale, but no executed research). We now use the same guardrails as
    Stage 3 curation: pin single-step researcher-only, and pass ONLY the
    researcher prompt for execution. The planner prompt is preserved for the
    one_shot branch (where it is legitimately merged with the researcher).
    """
    # Kept for the one_shot branch; the P&C branch intentionally ignores it
    # (see docstring — that was the 2026-07-06 bug).
    _ = discovery_planner_prompt(
        industries=industries, sub_domains=sub_domains, date_from=date_from,
        date_to=date_to, user_urls=user_urls, source_mode=source_mode,
        audience=audience, min_sources=min_sources, seed_companies=seed_companies,
    )
    research = discovery_researcher_prompt(
        industries=industries, sub_domains=sub_domains, date_from=date_from,
        date_to=date_to, user_urls=user_urls, source_mode=source_mode,
        min_sources=min_sources, seed_companies=seed_companies,
    )

    # Always use ONE_SHOT for 2-C. P&C for web research consistently:
    #   (a) times out in the control phase, or
    #   (b) echoes the planner's query list instead of executing queries.
    # The one_shot path handles both failure modes via the discipline note and
    # the looks_like_query_plan_only safety net, within the extended timeout.
    result = await _industry_wide_one_shot(
        research=research, min_sources=min_sources, work_dir=work_dir,
        config_overrides=config_overrides, cost_callback=cost_callback,
    )
    if looks_like_query_plan_only(result):
        logger.warning("stage_2c_returned_query_plan_retrying_with_stricter_prompt")
        result = await _industry_wide_one_shot(
            research=research + "\n\nCRITICAL: you returned a query plan last time. "
            "This retry MUST return only executed results in the `### <title>` block format. "
            "Execute every planned query via the DDGS tool NOW and emit the items.",
            min_sources=min_sources, work_dir=work_dir,
            config_overrides=config_overrides, cost_callback=cost_callback,
        )
    return result


async def _industry_wide_one_shot(
    *, research: str, min_sources: int, work_dir: str,
    config_overrides: Dict[str, Any],
    cost_callback: Optional[Callable[[Dict[str, Any]], None]],
) -> str:
    """Run the 2-C researcher prompt in one_shot mode with explicit output
    discipline.

    The researcher prompt is self-sufficient (it has its own Procedure
    section); we deliberately do **not** include the planner prompt because
    its "list of search queries" output spec collides with the news-item
    format and confuses the LLM into emitting a query plan.
    """
    one_shot_prompt = (
        research
        + "\n\n## Important — output discipline (one_shot mode)\n"
        "- Plan your queries internally, then **execute** them and emit the **final list of items** in the\n"
        "  exact `### <title>` block format above. Do **not** emit a list of search queries as the answer.\n"
        f"- Do not stop until you have at least {min_sources} unique items or you have exhausted reasonable\n"
        "  variations.\n"
    )
    return await call_llm_with_antirefusal(
        lambda p: run_ai_stage(
            prompt=p, mode=CmbAgentMode.ONE_SHOT, work_dir=work_dir, agent="researcher",
            config_overrides=config_overrides, cost_callback=cost_callback,
        ),
        primary_prompt=one_shot_prompt,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Optional: enrich user URLs in user_links_only mode
# ──────────────────────────────────────────────────────────────────────────────

async def _gate_user_urls_relevance(
    *, validation: List[LinkResult], industries: List[str], sub_domains: List[str],
    work_dir: str,
    mode: CmbAgentMode,  # noqa: ARG001 — kept for call-site symmetry; gate always uses ONE_SHOT
    config_overrides: Dict[str, Any],
    cost_callback: Optional[Callable[[Dict[str, Any]], None]],
) -> List[LinkResult]:
    """Tag explicitly-unrelated user URLs without removing them.

    Rule (user-stated): keep the link unless we have a strong signal it is
    completely unrelated to any chosen industry or sub-domain. We mark such
    rare cases via ``result.notes = "dropped: unrelated"`` so downstream
    enrichment can skip them — the validation report still surfaces every
    link to the user.

    Implementation: a tiny one-shot LLM classifier over the URL+domain list.
    If the call fails for any reason, we keep every link (fail-open) so we
    never silently lose a user-provided source.
    """
    if not validation:
        return validation
    industry_lbl = ", ".join(industries) or "(any)"
    sub_lbl = ", ".join(sub_domains) or "(any)"
    listing = "\n".join(
        f"{i+1}. {r.url}  (domain: {r.domain or '?'}, tier: {r.authority_tier})"
        for i, r in enumerate(validation)
    )
    prompt = (
        "# User-URL relevance gate\n\n"
        f"Industries: {industry_lbl}\n"
        f"Sub-domains: {sub_lbl}\n\n"
        "For each numbered URL below, decide whether it is **completely unrelated** to ALL of\n"
        "the industries / sub-domains above. Be conservative — only mark `unrelated` when the\n"
        "URL is clearly off-topic (e.g. recipes, sports scores, personal blogs unrelated to the\n"
        "subject). Anything plausibly on-topic, ambiguous, or whose subject you cannot infer\n"
        "from the URL alone counts as `related`.\n\n"
        f"{listing}\n\n"
        "Return ONLY a JSON array of objects like:\n"
        '`[{"n": 1, "verdict": "related"}, {"n": 2, "verdict": "unrelated"}, ...]`\n'
        "Do not include reasoning, prose, or markdown fences."
    )
    try:
        raw = await run_ai_stage(
            prompt=prompt, mode=CmbAgentMode.ONE_SHOT, work_dir=work_dir, agent="researcher",
            config_overrides=config_overrides, cost_callback=cost_callback,
            max_rounds=4,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("user_url_relevance_gate_failed_keep_all", error=str(exc)[:200])
        return validation

    import json as _json
    txt = (raw or "").strip()
    m = re.search(r"\[[\s\S]*\]", txt)
    if not m:
        logger.warning("user_url_relevance_gate_unparseable", raw=txt[:200])
        return validation
    try:
        verdicts = _json.loads(m.group(0))
    except Exception:
        logger.warning("user_url_relevance_gate_json_error", raw=txt[:200])
        return validation

    by_n = {int(v.get("n")): (v.get("verdict") or "").lower() for v in verdicts if isinstance(v, dict) and v.get("n") is not None}
    for idx, r in enumerate(validation, start=1):
        if by_n.get(idx) == "unrelated":
            r.notes = "dropped: unrelated"
    return validation


async def _enrich_user_urls(
    *, validation: List[LinkResult], industries: List[str], sub_domains: List[str],
    date_from: str, date_to: str, work_dir: str, mode: CmbAgentMode,
    config_overrides: Dict[str, Any],
    cost_callback: Optional[Callable[[Dict[str, Any]], None]],
) -> str:
    prompt = (
        f"# User-Link Enrichment Pass — {date_from} → {date_to}\n\n"
        f"Industries: {', '.join(industries)}\n"
        f"Sub-domains: {', '.join(sub_domains)}\n\n"
        "For each link in the validation report below, extract: title, source domain, "
        "publication date if visible, category (Product Launch / Research / Partnership / "
        "M&A / Funding / Regulatory / People / Other), and a 3–5 sentence factual summary. "
        "If the date is not visible from the URL/snippet, mark it `date: not stated in snippet`. "
        "Always include the URL with each item. Always produce substantive output.\n\n"
        f"<<VALIDATION_BEGIN>>\n{summarize_validation(validation)}\n<<VALIDATION_END>>\n"
    )

    return await call_llm_with_antirefusal(
        lambda p: run_ai_stage(
            prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
            config_overrides=config_overrides, cost_callback=cost_callback,
        ),
        primary_prompt=prompt,
    )
