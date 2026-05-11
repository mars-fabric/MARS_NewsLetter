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
from .mode_dispatcher import run_ai_stage
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
        logger.info(
            "user_urls_validated",
            total=len(validation),
            reachable=sum(1 for r in validation if r.reachable),
            authentic=sum(1 for r in validation if r.is_authentic),
        )

    sections: List[str] = [
        "# Stage 2 — Source Collection",
        "",
        f"_Coverage window: **{date_from} → {date_to}**_",
        f"_Source mode: **{source_mode.value}**_",
        f"_Pipeline mode: **{mode.value}**_",
        "",
    ]

    # ── 2. User URLs section (always rendered when we have them) ──────────────
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
    seed_companies: List[Dict[str, str]] = []
    if top_companies_count and top_companies_count > 0:
        company_md, seed_companies = await _discover_top_companies(
            industries=industries, sub_domains=sub_domains, top_n=top_companies_count,
            date_from=date_from, date_to=date_to,
            user_urls=user_urls if source_mode == SourceMode.COMBINED else [],
            audience=audience, work_dir=work_dir, mode=mode,
            config_overrides=config_overrides, cost_callback=cost_callback,
        )
        sections.append(f"## 2-A — Top {top_companies_count} Companies (web-discovered)")
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

    # In planning_and_control we hand the planner / researcher their instructions
    # explicitly; in one_shot we just send the merged prompt.
    if mode == CmbAgentMode.PLANNING_AND_CONTROL:
        researcher_md = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=config_overrides, cost_callback=cost_callback,
                plan_instructions=plan, researcher_instructions=research,
            ),
            primary_prompt=(
                f"Identify the top {top_n} companies in the chosen industries / sub-domains for the window "
                f"{date_from} → {date_to}. Follow the planner and researcher instructions exactly and emit "
                f"the markdown described."
            ),
        )
    else:
        # one_shot: send planner + researcher as a single document.
        merged = plan + "\n\n---\n\n" + research
        researcher_md = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=config_overrides, cost_callback=cost_callback,
            ),
            primary_prompt=merged,
        )

    companies = _parse_top_companies(researcher_md)
    logger.info("top_companies_parsed", requested=top_n, parsed=len(companies))
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

    if mode == CmbAgentMode.PLANNING_AND_CONTROL:
        researcher_instructions = (
            "Execute the per-company news extraction task. For each company, run a `site:<domain>` search "
            "and a free-form news search. Deduplicate by URL. Emit one `## <Company>` section per company "
            "in the exact format specified."
        )
        return await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=config_overrides, cost_callback=cost_callback,
                researcher_instructions=researcher_instructions,
            ),
            primary_prompt=prompt,
        )

    return await call_llm_with_antirefusal(
        lambda p: run_ai_stage(
            prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
            config_overrides=config_overrides, cost_callback=cost_callback,
        ),
        primary_prompt=prompt,
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
    """Industry-wide planner + researcher pass with a minimum-source mandate."""
    plan = discovery_planner_prompt(
        industries=industries, sub_domains=sub_domains, date_from=date_from,
        date_to=date_to, user_urls=user_urls, source_mode=source_mode,
        audience=audience, min_sources=min_sources, seed_companies=seed_companies,
    )
    research = discovery_researcher_prompt(
        industries=industries, sub_domains=sub_domains, date_from=date_from,
        date_to=date_to, user_urls=user_urls, source_mode=source_mode,
        min_sources=min_sources, seed_companies=seed_companies,
    )

    if mode == CmbAgentMode.PLANNING_AND_CONTROL:
        result = await call_llm_with_antirefusal(
            lambda p: run_ai_stage(
                prompt=p, mode=mode, work_dir=work_dir, agent="researcher",
                config_overrides=config_overrides, cost_callback=cost_callback,
                plan_instructions=plan, researcher_instructions=research,
            ),
            primary_prompt=(
                f"Collect at least {min_sources} unique sources for the newsletter on "
                f"{', '.join(industries)} ({date_from} → {date_to}). Follow the planner and researcher "
                f"instructions exactly and emit the markdown described."
            ),
        )
        # 2-C-specific guard: in P&C mode the researcher sometimes echoes the
        # planner's query list instead of executing it. Retry once in one_shot
        # with the researcher prompt only and an explicit "do not emit
        # queries" directive — that path is much more reliable.
        if looks_like_query_plan_only(result):
            logger.warning("stage_2c_returned_query_plan_falling_back_to_one_shot")
            return await _industry_wide_one_shot(
                research=research, min_sources=min_sources, work_dir=work_dir,
                config_overrides=config_overrides, cost_callback=cost_callback,
            )
        return result

    return await _industry_wide_one_shot(
        research=research, min_sources=min_sources, work_dir=work_dir,
        config_overrides=config_overrides, cost_callback=cost_callback,
    )


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
