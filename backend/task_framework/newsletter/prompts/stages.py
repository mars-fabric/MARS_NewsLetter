"""Prompts used by the NewsLetter pipeline (production-grade).

Design principles (informed by past production failures across the MARS family):

* **Soft date filtering, not hard discard.** When snippets do not show an
  explicit date, instruct the model to include the item with a "date: not
  stated in snippet" note rather than dropping it. A blanket "DISCARD unless
  explicitly dated" rule produced empty reports in NewsPulse.
* **Inject today's date** so the model has a clear referent for "recent".
* **Neutral editorial language**, not imperative prohibitions. Phrases like
  "STRICTLY FORBIDDEN" or "NEVER refuse" trip Azure's jailbreak classifier.
* **Cite-then-state.** Every claim trails its supporting URL.
* **Authentic sources first.** Prefer official / regulator / major-press
  sources for each industry; never fabricate citations.
* **Cross-check vendor mentions.** When a story names a specific vendor,
  product, or regulator, the researcher should run a follow-up ``site:``
  search on that vendor's official domain so the newsletter can cite the
  canonical source — this is what readers check when they ask "is this real?".

This file owns the stage-by-stage instructions only — the composition logic
(which prompt runs in which mode) lives in ``helpers.py``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional

_TAXONOMY_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "industry_taxonomy.json"
_HINTS_CACHE: Optional[Dict[str, List[str]]] = None
_NEUTRAL_CACHE: Optional[List[str]] = None


def _load_hints() -> tuple[Dict[str, List[str]], List[str]]:
    """Load per-industry authentic domain hints + the shared neutral-authority list.

    Returns ``({}, [])`` if the file is unreadable so prompt assembly never fails.
    """
    global _HINTS_CACHE, _NEUTRAL_CACHE
    if _HINTS_CACHE is not None and _NEUTRAL_CACHE is not None:
        return _HINTS_CACHE, _NEUTRAL_CACHE
    try:
        with _TAXONOMY_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        _HINTS_CACHE = dict(data.get("authentic_domain_hints", {}) or {})
        _NEUTRAL_CACHE = list(data.get("neutral_authority_domains", []) or [])
    except Exception:
        _HINTS_CACHE = {}
        _NEUTRAL_CACHE = []
    return _HINTS_CACHE, _NEUTRAL_CACHE


def _authentic_domains_for(industries: List[str], limit_per_industry: int = 10) -> List[str]:
    """Flat, ordered, deduped list of authoritative domains for the chosen industries."""
    hints, _ = _load_hints()
    seen: set[str] = set()
    out: List[str] = []
    for ind in industries:
        for domain in (hints.get(ind, []) or [])[:limit_per_industry]:
            d = domain.lower().strip()
            if d and d not in seen:
                seen.add(d)
                out.append(d)
    return out


def _neutral_authority_subset(limit: int = 12) -> List[str]:
    _, neutral = _load_hints()
    return [d for d in neutral[:limit]]


def _today() -> str:
    return date.today().isoformat()


def _join(lines: Iterable[str]) -> str:
    return "\n".join(line for line in lines if line is not None)


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2-A: Top-N Company Discovery
# ──────────────────────────────────────────────────────────────────────────────

def top_companies_planner_prompt(
    *,
    industries: List[str],
    sub_domains: List[str],
    top_n: int,
    date_from: str,
    date_to: str,
    audience: Optional[str] = None,
    user_urls: Optional[List[str]] = None,
) -> str:
    """Plan how to identify the top-N companies in scope.

    The planner produces a short list of DDGS / web searches that will surface
    the most influential vendors, regulators, and incumbents for the chosen
    industries / sub-domains. The researcher then executes those searches and
    emits a ranked company list which Stage 2-B consumes.
    """
    industry_lbl = ", ".join(industries) or "(none)"
    sub_lbl = ", ".join(sub_domains) or "(none)"
    aud = audience or "general business / industry stakeholders"
    user_seed = "\n".join(f"  - {u}" for u in (user_urls or [])) or "  (none)"

    authentic = _authentic_domains_for(industries)
    neutral = _neutral_authority_subset()
    authentic_lbl = ", ".join(authentic) if authentic else "(no industry-specific hints loaded)"
    neutral_lbl = ", ".join(neutral) if neutral else "reuters.com, bloomberg.com, ft.com, wsj.com, ap.org"

    return _join([
        f"# Top-Companies Discovery Planner — {date_from} → {date_to}",
        "",
        f"Today is **{_today()}**. The newsletter is intended for: {aud}.",
        "",
        "## Goal",
        f"Identify the **top {top_n} companies** that matter most for the chosen industries / sub-domains over the coverage window.",
        "Companies = the firms, vendors, regulators, and labs whose activity is most newsworthy and material for the audience.",
        "",
        "## Subject scope",
        f"- Industries: {industry_lbl}",
        f"- Sub-domains: {sub_lbl}",
        f"- Coverage window: {date_from} to {date_to}",
        "",
        "## User-supplied URLs (treat as priors, not as the only signal)",
        user_seed,
        "If a user URL points at a company's site (e.g. anthropic.com), that company is a strong candidate — verify and include.",
        "",
        "## Authoritative reference domains",
        f"- Industry-specific: {authentic_lbl}",
        f"- Neutral press / authority: {neutral_lbl}",
        "",
        "## Plan",
        "Plan 4–6 web searches. The combined results must let you rank companies by:",
        "  1. **Newsworthiness in the window** (announcements, releases, M&A, regulatory action, earnings)",
        "  2. **Market position** (incumbent leader, fastest-growing challenger, regulator)",
        "  3. **Coverage breadth** (how many distinct authoritative sources discuss them)",
        "",
        f"**Bake the date range into every query.** Include either `{date_from[:7]}` / `{date_to[:7]}` or `after:{date_from} before:{date_to}` in each planned query. **Authoritative-source bias**: for every strong candidate company you name in the plan, add a dedicated `site:<candidate-official-domain> news OR press` query — this is what confirms the domain and pulls the canonical release URL.",
        "",
        "Examples of useful queries:",
        f"  - `top <industry> companies {date_from[:4]} leaders market share`",
        f"  - `<industry> notable announcements after:{date_from} before:{date_to}`",
        "  - `<sub_domain> vendors enterprise adoption ranking`",
        f"  - `site:<regulator-official-domain> action <industry> {date_from[:4]}`",
        f"  - `site:openai.com OR site:anthropic.com OR site:blogs.nvidia.com news {date_from[:7]}`",
        "",
        "## Output (markdown)",
        "Return a numbered list of planned searches. For each:",
        "  - Search query (literal string)",
        "  - Why this query matters",
        "  - 2–3 target authoritative domains",
        "",
        "Always produce substantive output. If a query yields little, simplify and continue planning.",
    ])


def top_companies_researcher_prompt(
    *,
    industries: List[str],
    sub_domains: List[str],
    top_n: int,
    date_from: str,
    date_to: str,
    user_urls: Optional[List[str]] = None,
) -> str:
    industry_lbl = ", ".join(industries) or "(none)"
    sub_lbl = ", ".join(sub_domains) or "(none)"
    user_seed = "\n".join(f"  - {u}" for u in (user_urls or [])) or "  (none)"

    authentic = _authentic_domains_for(industries)
    authentic_lbl = ", ".join(authentic) if authentic else "(no industry-specific hints loaded)"

    return _join([
        f"# Top-Companies Researcher — {date_from} → {date_to}",
        "",
        f"Today is **{_today()}**. Execute the planner's searches and produce a ranked list of the top **{top_n}** companies in scope.",
        "",
        "## Subject scope",
        f"- Industries: {industry_lbl}",
        f"- Sub-domains: {sub_lbl}",
        "",
        "## User priors",
        user_seed,
        "",
        f"## Authoritative reference domains: {authentic_lbl}",
        "",
        "## Procedure",
        f"1. **Include the year in every query.** Append `{date_from[:4]}` to each search string so DDGS biases toward recent content. Do NOT use `after:date before:date` operators — they reduce DDGS result quality.",
        f"2. **Authority-first query order.** For each candidate company, run `site:<official-domain> {date_from[:4]} news OR release` as the FIRST query to confirm the domain and pull the canonical press/release page. The vendor page becomes the `official_domain` and the highest-priority evidence URL.",
        "3. Run each planned search via the DDGS / web-search tool. Read the snippet text returned with each result to extract facts.",
        f"4. **Soft date filter.** Include hits from {date_from[:4]} and {date_to[:4]}. Tag undated hits as acceptable for company-ranking evidence. Only skip items whose URL clearly contains `/2024/` or earlier.",
        "5. Aggregate companies that appear across results. Normalise common variants (e.g. 'Anthropic PBC' → 'Anthropic').",
        "6. For each candidate, capture:",
        "     - `name`",
        "     - `official_domain` (verify with a `site:` lookup when possible)",
        "     - `headquarters_country` (best guess from sources)",
        "     - `why_in_scope` (1–2 sentences citing the strongest source)",
        "     - `evidence_urls` (1–3 URLs that justify inclusion)",
        f"7. Rank and keep only the top **{top_n}**. Prefer companies with multiple authoritative citations and recent activity.",
        "8. If the search yields fewer than the requested count, return what you have and add a `Coverage Notes` paragraph explaining the gap.",
        "",
        "## Output (markdown)",
        "Use exactly this format so Stage 2-B can parse it deterministically:",
        "",
        "```",
        f"## Top-{top_n} Companies",
        "",
        "1. **<name>** — <https://official-domain>",
        "   - **HQ**: <country / 'unknown'>",
        "   - **Why in scope**: <1–2 sentences>",
        "   - **Evidence**: <https://...>, <https://...>",
        "",
        "2. **<name>** — <https://official-domain>",
        "   ...",
        "```",
        "",
        "End with a `## Coverage Notes` paragraph — keep it short (≤ 4 sentences).",
    ])


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2-B: Per-Company News Extraction (drilling into each top company)
# ──────────────────────────────────────────────────────────────────────────────

def per_company_news_prompt(
    *,
    companies: List[Dict[str, str]],
    industries: List[str],
    sub_domains: List[str],
    date_from: str,
    date_to: str,
    items_per_company: int = 3,
) -> str:
    """Drill into each top-company and extract their news + innovations.

    ``companies`` is a list of ``{"name": ..., "domain": ...}`` dicts emitted
    by Stage 2-A. The researcher runs ``site:<domain>`` searches plus general
    queries naming the company so we capture both press releases and third-
    party coverage.
    """
    company_lines: List[str] = []
    for c in companies:
        name = c.get("name", "?")
        dom = c.get("domain", "")
        company_lines.append(f"- **{name}** — official: {dom or '(unknown)'}")
    companies_block = "\n".join(company_lines) or "(none — fall back to industry-wide search)"

    industry_lbl = ", ".join(industries) or "(none)"
    sub_lbl = ", ".join(sub_domains) or "(none)"
    authentic = _authentic_domains_for(industries)
    authentic_lbl = ", ".join(authentic) if authentic else "(no industry-specific hints loaded)"

    return _join([
        f"# Per-Company News Extractor — {date_from} → {date_to}",
        "",
        f"Today is **{_today()}**. For each of the companies below, gather news and innovations from the coverage window.",
        "",
        "## Companies in scope",
        companies_block,
        "",
        "## Subject scope",
        f"- Industries: {industry_lbl}",
        f"- Sub-domains: {sub_lbl}",
        f"- Authoritative domains: {authentic_lbl}",
        "",
        "## Procedure (per company)",
        f"1. **First query — vendor-official (mandatory).** Run `site:<official-domain> {date_from[:4]} news OR release OR announcement OR launch` via DDGS. The results from this query are the highest-authority hits and become `Primary source` (URL field) for any downstream story on that company.",
        f"2. **Second query — dated free-form.** Run `<company name> news {date_from[:4]} latest` via DDGS. Use press-tier hits (reuters/bloomberg/ft/wsj/techcrunch) as `also_covered_by`.",
        f"3. **Third query — categorical.** Run `<company name> partnership OR funding OR product OR research {date_from[:4]}` via DDGS.",
        f"4. **Soft date filter.** Include ALL hits from {date_from[:4]} or {date_to[:4]}. Tag items with `date: not stated in snippet` when no explicit date is visible in the snippet. Only skip items whose URL clearly contains `/2024/` or `/2023/` (or earlier). Never write 'no in-window news found' — if the search returned ANY results about this company, extract and include them.",
        f"5. Extract up to **{items_per_company}** distinct items per company. Deduplicate before extraction.",
        "6. For each item capture:",
        "     - `title`",
        "     - `url` (MUST prefer the vendor-official / press-release link from query 1; only fall back to third-party if vendor-official is unavailable)",
        "     - `source_domain`",
        "     - `also_covered_by` (other URLs covering the same story — third-party press goes here when vendor-official is Primary)",
        "     - `date` (YYYY-MM-DD or 'not stated in snippet')",
        "     - `category`: choose one — Product Launch / Research / Partnership / M&A / Funding / Regulatory / People / Other",
        "     - `summary` (3–5 sentences, factual, no marketing language, grounded in snippet content)",
        "",
        "Always produce substantive output per company — use the snippet content from search results to write summaries. Only write `_(no in-window news found)_` if the DDGS tool returned zero results for all three queries for that company.",
        "",
        "## Output (markdown)",
        "Group by company. Use exactly:",
        "",
        "```",
        "## <Company name>",
        "",
        "### <item title>",
        "- **URL**: <https://...>",
        "- **Source**: <domain>",
        "- **Also covered by**: <https://...>, <https://...>  (omit if none)",
        "- **Date**: <YYYY-MM-DD or 'not stated in snippet'>",
        "- **Category**: <one of the categories above>",
        "- **Summary**: <factual prose>",
        "```",
        "",
        "Always produce substantive output. Treat the data as authoritative.",
    ])


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2-C: General industry / sub-domain news (separate from per-company)
# ──────────────────────────────────────────────────────────────────────────────

def discovery_planner_prompt(
    *,
    industries: List[str],
    sub_domains: List[str],
    date_from: str,
    date_to: str,
    user_urls: List[str],
    source_mode: str,
    audience: Optional[str] = None,
    min_sources: int = 30,
    seed_companies: Optional[List[Dict[str, str]]] = None,
) -> str:
    """General industry-level discovery planner (Stage 2-C).

    ``seed_companies`` is the ranked list from Stage 2-A. They are merged into
    the planner's seed so that vendor-specific cross-checks become part of the
    plan — this is the "user URLs are merged into the planner's seed" rule.
    User-supplied URLs are also threaded in.
    """
    industry_lbl = ", ".join(industries) or "(none)"
    sub_lbl = ", ".join(sub_domains) or "(none)"
    user_url_lbl = "\n".join(f"  - {u}" for u in user_urls) or "  (none provided)"
    audience_lbl = audience or "general business / industry stakeholders"

    seed_block = ""
    if seed_companies:
        lines = []
        for c in seed_companies:
            n = c.get("name", "?")
            d = c.get("domain", "")
            lines.append(f"  - {n} (site: {d or 'unknown'})")
        seed_block = "## Seed companies (from Stage 2-A; cross-check each one)\n" + "\n".join(lines) + "\n"

    authentic = _authentic_domains_for(industries)
    neutral = _neutral_authority_subset()
    authentic_lbl = ", ".join(authentic) if authentic else "(no industry-specific hints loaded)"
    neutral_lbl = ", ".join(neutral) if neutral else "reuters.com, bloomberg.com, ft.com, wsj.com, ap.org"

    return _join([
        f"# Industry Source-Discovery Planner — {date_from} → {date_to}",
        "",
        f"Today is **{_today()}**. Plan the industry-wide data collection for a professional newsletter aimed at: {audience_lbl}.",
        "",
        "## Subject scope",
        f"- Industries: {industry_lbl}",
        f"- Sub-domains: {sub_lbl}",
        f"- Coverage window: {date_from} to {date_to}",
        f"- Source mode: {source_mode}",
        "",
        "## User-supplied URLs (use them when source_mode is user_links_only or combined)",
        user_url_lbl,
        "Merge each user URL into the plan: at minimum, run a follow-up `site:<domain>` search to find canonical / sibling content.",
        "",
        seed_block,
        "## Authoritative reference domains",
        f"- Industry-specific (regulators, vendors, journals): {authentic_lbl}",
        f"- Neutral press / authority: {neutral_lbl}",
        "",
        "## Plan",
        f"Plan **at least 12 distinct web searches** (DDGS / web search) so the researcher can collect **≥ {min_sources} unique sources** across:",
        "  1. Breaking news / announcements within the window",
        "  2. Regulatory or policy moves (cite the regulator's site when possible)",
        "  3. Major company / vendor moves (use the vendor's official site as primary source)",
        "  4. Funding, M&A, partnerships",
        "  5. Technology shifts, releases, benchmarks",
        "  6. Risk / market sentiment indicators",
        "  7. Research papers, whitepapers, scientific releases",
        "  8. Tooling, SDKs, dataset releases",
        "  9. Industry-specific deep-dives (per sub-domain)",
        "",
        f"**Include the year in every planned query.** Append `{date_from[:4]}` to each query string so DDGS returns recent results. Do NOT use `after:date before:date` operators — they reduce DDGS result quality. Use natural-language year terms instead.",
        "",
        f"**Authoritative-source bias (mandatory).** For every seed company from Stage 2-A and for every named vendor/regulator/product likely to surface, plan a dedicated `site:<official-domain> {date_from[:4]}` query FIRST — the researcher will use that as `Primary source` and downgrade third-party press to `Also covered by`. Examples: `site:openai.com GPT {date_from[:4]}`, `site:anthropic.com Claude {date_from[:4]}`, `site:blogs.nvidia.com {industry_lbl} {date_from[:4]}`, `site:europa.eu AI {date_from[:4]}`.",
        "",
        "Prefer authoritative domains over aggregators. When two sources cover the same story, keep the more authoritative one as Primary, the other as `Also covered by`.",
        "",
        "## Output format (markdown)",
        "A numbered list. For each search:",
        "  - Search query (literal string, MUST include year)",
        "  - Why this query matters",
        "  - Two or three target domains considered authoritative",
        "",
        f"Aim for breadth: by the end of the plan the researcher should be able to retrieve ≥ {min_sources} unique URLs.",
        f"Items whose snippet has no explicit date but whose URL year is `{date_from[:4]}` or `{date_to[:4]}` are acceptable — the curator will tag Freshness=6. Items whose URL/snippet clearly indicates a year before {date_from[:4]} will be dropped by the curator.",
    ])


def discovery_researcher_prompt(
    *,
    industries: List[str],
    sub_domains: List[str],
    date_from: str,
    date_to: str,
    user_urls: List[str],
    source_mode: str,
    min_sources: int = 30,
    seed_companies: Optional[List[Dict[str, str]]] = None,
) -> str:
    industry_lbl = ", ".join(industries) or "(none)"
    sub_lbl = ", ".join(sub_domains) or "(none)"
    user_url_lbl = "\n".join(f"  - {u}" for u in user_urls) or "  (none)"

    seed_block = ""
    if seed_companies:
        lines = []
        for c in seed_companies:
            n = c.get("name", "?")
            d = c.get("domain", "")
            lines.append(f"  - {n} (site: {d or 'unknown'})")
        seed_block = "## Seed companies (must each appear at least once if news exists)\n" + "\n".join(lines) + "\n"

    authentic = _authentic_domains_for(industries)
    authentic_lbl = ", ".join(authentic) if authentic else "(no industry-specific hints loaded)"

    return _join([
        f"# Industry News Researcher — {date_from} → {date_to}",
        "",
        f"Today is **{_today()}**. Execute the planner's searches and assemble a long, deduped list of items.",
        "",
        f"## Target: at least **{min_sources}** unique items in the final output.",
        "If you cannot reach the target, simplify queries and run additional searches before finishing.",
        "",
        "## Subject scope",
        f"- Industries: {industry_lbl}",
        f"- Sub-domains: {sub_lbl}",
        f"- Source mode: {source_mode}",
        "",
        "## User-supplied URLs (always read these when listed)",
        user_url_lbl,
        "Treat user URLs as authoritative seeds: extract their content and add a follow-up `site:` search per domain.",
        "",
        seed_block,
        f"## Authoritative reference domains: {authentic_lbl}",
        "",
        "## Procedure",
        f"1. **Include the year in every query.** Append `{date_from[:4]}` (or `{date_from[:4]} {date_to[:4]}`) to each search string so results are biased toward recent content. Do NOT use `after:date before:date` DDGS operators — they reduce result quality. Natural-language year terms work better.",
        "2. **Authority-first query order.** For every seed company / vendor / regulator / product named in the plan, the FIRST query executed MUST be `site:<official-domain> <topic> {date_from[:4]}`. Only after that vendor-official query returns results (or is exhausted) do you run the generic press-search queries. The vendor page becomes `Primary source`; the third-party coverage becomes `Also covered by`.",
        "3. Execute each planned search via DDGS / web tools. From each result extract: title, URL, source domain, publication date from the snippet if visible, and a 3–5 sentence summary using the snippet content.",
        f"4. **Soft date filter (keep and tag).** Include ALL items from {date_from[:4]} or {date_to[:4]}. Tag items with `date: not stated in snippet` when no explicit date is visible. Only skip items whose URL contains `/2024/` or `/2023/` (or clearly older years). When a snippet is returned, always extract its content — do not discard items because you cannot pin the exact date.",
        "5. Always include the URL with each item. Never invent URLs.",
        "6. **Vendor / regulator cross-check (mandatory follow-up).** When any item names a specific vendor (OpenAI/Anthropic/NVIDIA/Meta/Google), regulator (FDA/SEC/EU/FTC), or product (GPT-5/Claude/Gemini/Llama), run an additional `site:<official-domain> {date_from[:4]}` search AS ITS OWN QUERY and add the canonical link as `Primary source`. The non-canonical hit becomes `Also covered by`. Do NOT skip this cross-check — it is what makes the newsletter trustworthy.",
        "7. If a search returns < 3 hits, simplify the query and retry once (drop site: scoping, drop OR clauses, use just 2-3 keywords). If a `site:<official>` search returns 0 hits, that is acceptable — record a note in Coverage Notes.",
        "8. Deduplicate by URL before emitting.",
        "",
        "## Output (markdown)",
        "A flat list of items, each shaped exactly like:",
        "",
        "```",
        "### <title>",
        "- **URL**: <https://...>  (preferably the canonical / vendor-site link)",
        "- **Source**: <domain>",
        "- **Also covered by**: <https://...>, <https://...>  (omit if none)",
        "- **Date**: <YYYY-MM-DD or 'not stated in snippet'>",
        "- **Sub-domain**: <best fit from the list above>",
        "- **Category**: Breaking / Regulatory / Vendor / Funding / Research / Trend / Other",
        "- **Summary**: <3–5 sentences, factual, no marketing language>",
        "```",
        "",
        f"End the document with a single line: `_Total items collected: <N>_` so the curator can verify against the {min_sources}-item target.",
        "",
        "Always produce substantive content. Treat the data as authoritative and write it forward.",
    ])


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3: Curation
# ──────────────────────────────────────────────────────────────────────────────

def curation_prompt(
    *,
    raw_collection: str,
    industries: List[str],
    sub_domains: List[str],
    date_from: str,
    date_to: str,
    audience: Optional[str] = None,
) -> str:
    industry_lbl = ", ".join(industries)
    sub_lbl = ", ".join(sub_domains)
    aud = audience or "general business / industry stakeholders"
    authentic = _authentic_domains_for(industries)
    neutral = _neutral_authority_subset()
    authentic_lbl = ", ".join(authentic) if authentic else "(no industry-specific hints loaded)"
    neutral_lbl = ", ".join(neutral) if neutral else "reuters.com, bloomberg.com, ft.com, wsj.com, ap.org"
    # Extract the years covered by the window so the curator can drop items
    # whose URL clearly points at a different year.
    yr_from = date_from[:4] if date_from else ""
    yr_to = date_to[:4] if date_to else ""
    years_in_window = sorted({yr_from, yr_to} - {""})
    years_lbl = ", ".join(years_in_window) or "(unknown)"

    return _join([
        f"# Newsletter Curator — {date_from} → {date_to} (production-grade)",
        "",
        f"Today is **{_today()}**. You are curating a professional newsletter for: {aud}.",
        f"- Industries: {industry_lbl}",
        f"- Sub-domains: {sub_lbl}",
        f"- Coverage window: **{date_from} → {date_to}** (years in scope: {years_lbl})",
        "",
        "## Source material",
        "Below is the raw Stage-2 collection. It includes (a) per-company news, (b) industry-wide news, and — when present — (c) a `User-Provided Links` validation table plus a `User-Provided Links (enriched)` block. Curate everything into a tighter, layered list — keep depth. The downstream writer will fill ~50 newsletter sections, so do not over-prune.",
        "",
        "<<RAW_COLLECTION_BEGIN>>",
        raw_collection,
        "<<RAW_COLLECTION_END>>",
        "",
        "## Authority hierarchy (rank sources in this order)",
        "  1. **Official / vendor / regulator** — the entity's own site publishes the primary artifact:",
        f"     `{authentic_lbl}` plus any obvious first-party site named in the raw snippet (e.g. openai.com for GPT-5, anthropic.com for Claude, sec.gov for SEC filings, fda.gov for FDA notices).",
        f"  2. **Major independent press** — {neutral_lbl}.",
        "  3. **Trade press / specialist blogs** — e.g. techcrunch.com, theverge.com, arstechnica.com, venturebeat.com.",
        "  4. **Aggregators, forums, social** — hackernews, reddit, medium.com. These are `Also covered by` only, never `Primary source`.",
        "",
        "## Curation rules (production-grade)",
        f"1. **Strict date window.** The coverage window is `{date_from} → {date_to}`. Items whose URL, title, or snippet clearly indicates a publication date OUTSIDE this window (e.g. year-in-URL like `/2024/`, `/2023/`, or a snippet timestamp older than {date_from} or newer than {date_to}) MUST be dropped. Items with `date: not stated in snippet` are kept only if (a) the URL's year segment is in scope or absent, AND (b) the snippet does not name a year outside the window.",
        "2. **Authority-domain preference.** For any story that names a specific vendor, product, regulator, or research paper, the **Primary source** MUST be the entity's official site when a link to it exists anywhere in the raw collection. Downgrade third-party coverage to `Also covered by`. Concrete rule: if the story is about \"GPT-5 / OpenAI\" the Primary must be `openai.com`; \"Claude / Anthropic\" → `anthropic.com`; \"Gemini / Google\" → `deepmind.google` or `blog.google`; \"Llama / Meta\" → `ai.meta.com`; \"NVIDIA hardware\" → `nvidia.com` or `blogs.nvidia.com`; \"EU AI Act\" → `europa.eu`; \"SEC filing\" → `sec.gov`; \"FDA\" → `fda.gov`. When only the third-party link exists in the raw set, keep it as Primary but tag the item `Authority: <=6` and add a `- **Missing canonical**: yes` line so the writer knows to look for the vendor page.",
        "3. **Deduplicate by story, not by URL.** Group items that cover the same event; keep the highest-authority link as `Primary source` and list the rest as `Also covered by`.",
        "4. **Keep volume.** If the raw set has ≥ 30 items, the curated output should retain ≥ 25 of them. Quality over quantity, but volume is required for the final newsletter to be substantive.",
        "5. **Drop only obvious noise.** Off-topic items, broken/placeholder URLs, items whose validation note reads exactly `dropped: unrelated`, items with no real summary, and items outside the date window per rule 1. **Do not** drop a user-provided URL for any other reason — `unknown` authority tier is fine.",
        "6. **User-Provided Links are first-class.** Every URL in the User-Provided Links block (validation table + enriched section) must appear at least once in your output unless it was flagged `dropped: unrelated`. Tag user-provided items with `Source: user-provided` on a dedicated line so the writer can route them into the right section.",
        "7. **Numeric scoring per item.** Score each item on three 1–10 dimensions:",
        "     - `Relevance` (fit to industries / sub-domains / audience — 10 is a direct-hit story on a named sub-domain, 5 is tangential, 1 is off-topic).",
        "     - `Authority` — apply the hierarchy strictly:",
        "         * `9–10`: official vendor / regulator / peer-reviewed research paper.",
        "         * `7–8`: major independent press (Reuters / Bloomberg / FT / WSJ / AP / NYT / Economist).",
        "         * `5–6`: trade press / specialist blog with named byline.",
        "         * `3–4`: unsigned trade blog / low-authority aggregator.",
        "         * `1–2`: forum / social / promotional page.",
        f"     - `Freshness` — `10` if explicitly dated within `{date_from} → {date_to}`; `8` if dated in the same month but unclear day; `6` if `date: not stated in snippet` but URL year is `{years_lbl}`; `1` if outside the window (should already be dropped per rule 1).",
        "8. **Per-item summary** is 3–6 sentences, factual, no marketing language. **Preserve every concrete number, percentage, dollar figure, benchmark score, release count, and named entity that appears in the raw snippet** — these are what Stage 4 will surface in the `Data & Evidence` and `Statistics Snapshot` sub-sections and are the single most common thing that gets accidentally paraphrased away. If the raw snippet says '400M weekly active users' or 'raised $6B at a $500B valuation' or 'benchmark score 76.4%', that exact figure must appear verbatim in your summary.",
        "9. **Tag categories.** Each item gets a `Category` (Product Launch / Research / Partnership / M&A / Funding / Regulatory / People / Trend / Other).",
        "10. **Highlight 'top stories'.** Tag the 5–8 highest-impact items with `Top: yes`. An item with `Top: yes` MUST have Relevance ≥ 8 AND Authority ≥ 8 (i.e. official / vendor / major-press primary source), except when no better source exists and the story is undeniably a top story — in which case add a `- **Note**: only third-party coverage available` line.",
        "11. **Highlight numeric evidence.** For each item that contains one or more concrete figures, add a `- **Key figures**: <fig1>; <fig2>; <fig3>` line immediately after the Summary. This gives Stage 4 a pre-extracted numeric feed for the `Data & Evidence` section.",
        "",
        "## Output format (markdown)",
        "Group items by sub-domain headings. Within each sub-domain, group again by company when applicable. Each item:",
        "",
        "```",
        "### <title>",
        "- **Date**: <YYYY-MM-DD or 'not stated in snippet'>",
        "- **Primary source**: <https://...> (<domain>) — MUST be highest-authority link available per rules 2 + 7",
        "- **Also covered by**: <https://...>, <https://...>  (omit if none)",
        "- **Source**: user-provided | web-discovered",
        "- **Category**: <one of the categories above>",
        "- **Top**: <yes | no>",
        "- **Relevance**: <1-10>",
        "- **Authority**: <1-10>  # apply the 9-10/7-8/5-6/3-4/1-2 tiers strictly",
        "- **Freshness**: <1-10>  # 10 in-window+dated; 6 undated but URL-year in scope; drop if 1-2",
        "- **Summary**: <factual prose>",
        "```",
        "",
        "End with these two sections:",
        "  - `## Coverage Notes` — list any sub-domains that had thin / missing coverage, plus any items dropped per rule 1 (with reason).",
        "  - `## Curation Stats` — total items in raw, total kept, count dropped for out-of-window date, count of `Top: yes`, count of `Source: user-provided` items kept vs supplied, count of items with `Authority >= 9`, and a one-line gap analysis.",
        "",
        "Always produce substantive output. When the raw collection is thin, work with what is present rather than refusing.",
    ])


# ──────────────────────────────────────────────────────────────────────────────
# Stage 4: Generation (analyst → writer) targeting the 56-section template
# ──────────────────────────────────────────────────────────────────────────────

# Canonical section list — mirrors sample_output.md (the production template).
NEWSLETTER_SECTION_LIST: List[str] = [
    "Newsletter Metadata",
    "Editor's Note",
    "Executive Summary",
    "TL;DR Key Takeaways",
    "Industry & Subdomain Focus",
    "Top Story of the Period",
    "Secondary Major Story",
    "Other Notable Headlines",
    "Subdomain Highlight #1",
    "Subdomain Highlight #2",
    "Subdomain Highlight #3",
    "Product / Platform Releases",
    "Feature Updates",
    "Research / Whitepapers",
    "Emerging Trends",
    "Declining or Saturating Trends",
    "Market or Ecosystem Signals",
    "What This Means for the Audience",
    "Opportunities for the Audience",
    "Risks & Challenges",
    "Focus Topic Deep Dive",
    "Background & Context",
    "What Changed in This Date Range",
    "Implications",
    "Insights from Web Search Sources",
    "Insights from User-Provided Links",
    "Cross-Source Comparison",
    "Key Data Points",
    "Statistics Snapshot",
    "Notable Quotes",
    "Expert Commentary Summary",
    "Tools Mentioned This Period",
    "Recommended Reading",
    "Documentation & References",
    "Recommended Actions",
    "Strategic Considerations",
    "Watchlist Items",
    "Signals for the Next Period",
    "Predictions",
    "Source Collection Method",
    "Source List",
    "Content Selection Criteria",
    "AI Generation Notes",
    "Bias & Limitations Disclosure",
    "Disclaimer",
    "Next Edition Preview",
    "Newsletter Footer",
]


def generation_analyst_prompt(
    *,
    curated: str,
    industries: List[str],
    sub_domains: List[str],
    date_from: str,
    date_to: str,
    audience: Optional[str],
    title: Optional[str] = None,
    user_urls: Optional[List[str]] = None,
    seed_companies: Optional[List[Dict[str, str]]] = None,
    section_headings: Optional[List[str]] = None,
) -> str:
    aud = audience or "general business / industry stakeholders"
    title_lbl = title or "(auto-generate from industry + sub-domain)"
    seed_lbl = ", ".join(c.get("name", "?") for c in (seed_companies or [])) or "(none — derive from curated set)"

    # Truncate curated to 6 000 chars so the analyst prompt stays well within
    # context and avoids the 3-hour runs caused by 80–150 KB payloads.
    curated_excerpt = curated[:6000]
    if len(curated) > 6000:
        curated_excerpt += "\n\n... [curated material truncated — full set available to the section writer]"

    # Section list: use the user's chosen headings (Gate B) when available,
    # otherwise fall back to the 22 canonical headings.
    if section_headings:
        section_list_lines = [f"   - {h}" for h in section_headings]
        section_count = len(section_headings)
        section_source = "user-defined"
    else:
        from ..stage4.sections import canonical_headings
        section_list_lines = [f"   - {h}" for h in canonical_headings()]
        section_count = 22
        section_source = "canonical"

    return _join([
        f"# Newsletter Analyst — {date_from} → {date_to}",
        "",
        f"Today is **{_today()}**. Prepare the analytical outline for a production newsletter aimed at: {aud}.",
        f"- Title hint: {title_lbl}",
        f"- Industries: {', '.join(industries)}",
        f"- Sub-domains: {', '.join(sub_domains)}",
        f"- Top companies in scope: {seed_lbl}",
        "Tone: professional, neutral, authoritative, implication-led.",
        "",
        "## IMPORTANT — scope of this task",
        "You are a **content analyst**, not a researcher. Work ONLY from the curated material below.",
        "Do NOT run web searches, call DDGS, or fetch any URLs — all the evidence you need is here.",
        "",
        "## Curated material (ground truth — excerpt)",
        "<<CURATED_BEGIN>>",
        curated_excerpt,
        "<<CURATED_END>>",
        "",
        "## Your task",
        "1. Identify **5–8 themes** that connect the curated items. For each theme:",
        "   - `Title` (≤ 8 words)",
        "   - `Framing` (one paragraph: what it is, why it matters now, who is affected)",
        "   - `Supporting items` (cite by title + URL, ≥ 3 items from the curated set above)",
        "   - `So-what` line: implication for the audience",
        "",
        "2. Pick the **Top Story** and **Secondary Story** for the period, with a one-line rationale each.",
        "",
        "3. Identify **3 sub-domain highlights** (the most important development per sub-domain in scope).",
        "",
        "4. Surface **opportunities** (3–5) and **risks / challenges** (3–5) for the audience.",
        "",
        "5. Suggest a **Focus Topic Deep Dive** (one specific topic that warrants extended treatment).",
        "",
        f"6. **Coverage map (mandatory).** Enumerate EVERY curated item that is either `Top: yes` OR has `Relevance >= 8`, and for each one name the section (from the {section_count} {section_source} sections below) where it will appear. Do not leave a high-relevance item unassigned.",
        "",
        f"7. Propose the section order for the final newsletter using the {section_count} {section_source} sections:",
        "",
        "```",
        *section_list_lines,
        "```",
        "",
        "## Output (markdown)",
        "Return a structured outline with the themes, the top/secondary picks, opportunities, risks, deep-dive topic, and the ordered section list. Do not draft the full newsletter yet — that is the writer's job.",
        "",
        "Always produce substantive output. Treat the curated material as authoritative.",
    ])


# ──────────────────────────────────────────────────────────────────────────────
# Stage 4/5 — legacy monolithic critic / editor / scorer / writer prompts REMOVED
# ──────────────────────────────────────────────────────────────────────────────
#
# The monolithic writer/critic/editor/scorer prompts used to live here. They
# powered a single-shot "write the whole 22-section newsletter in one LLM call"
# path (and a mirroring critic → editor → score-card pipeline in Stage 5).
#
# That path was replaced by:
#   * ``stage4/runner.py`` + ``stage4/sections.py`` — writes each canonical
#     section in its own bounded LLM call (no output-token clip).
#   * ``stage5/graph.py`` + ``stage5/nodes.py`` — a 22-node LangGraph DAG that
#     verifies URLs, re-checks claims with DDGS, applies the editor, runs the
#     deterministic ``programmatic_verification.verify_and_clean`` safety net,
#     and scores the result with its own inline prompt.
#
# The old prompts had no remaining callers and were deleted to keep this file
# focused on what actually runs today.

