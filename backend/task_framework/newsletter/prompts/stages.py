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
        "Examples of useful queries:",
        "  - `top <industry> companies 2025 2026 leaders market share`",
        "  - `<industry> notable announcements <date_from> <date_to>`",
        "  - `<sub_domain> vendors enterprise adoption ranking`",
        "  - `<regulator name> action <industry>`  (use the relevant regulator domain in target list)",
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
        "1. Run each planned search via the DDGS / web-search tool.",
        "2. Aggregate companies that appear across results. Normalise common variants (e.g. 'Anthropic PBC' → 'Anthropic').",
        "3. For each candidate, capture:",
        "     - `name`",
        "     - `official_domain` (verify with a `site:` lookup when possible)",
        "     - `headquarters_country` (best guess from sources)",
        "     - `why_in_scope` (1–2 sentences citing the strongest source)",
        "     - `evidence_urls` (1–3 URLs that justify inclusion)",
        f"4. Rank and keep only the top **{top_n}**. Prefer companies with multiple authoritative citations and recent activity.",
        "5. If the search yields fewer than the requested count, return what you have and add a `Coverage Notes` paragraph explaining the gap.",
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
        "1. Run a `site:<official-domain> 2025 OR 2026 announcement OR release OR launch` search via DDGS.",
        "2. Run a free-form `<company name> news <date_from>..<date_to>` search.",
        "3. Run a `<company name> partnership OR funding OR product launch OR research` search.",
        f"4. Extract up to **{items_per_company}** distinct items per company. Deduplicate before extraction.",
        "5. For each item capture:",
        "     - `title`",
        "     - `url` (prefer the official / vendor-site link)",
        "     - `source_domain`",
        "     - `also_covered_by` (other URLs covering the same story)",
        "     - `date` (YYYY-MM-DD or 'not stated in snippet')",
        "     - `category`: choose one — Product Launch / Research / Partnership / M&A / Funding / Regulatory / People / Other",
        "     - `summary` (3–5 sentences, factual, no marketing language)",
        "",
        "If a company has nothing in the window, write `_(no in-window news found)_` for that company and continue.",
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
        "**Authoritative-source bias.** For any story that names a specific vendor, regulator, or product, plan a follow-up `site:<official-domain>` query so the newsletter cites the canonical source.",
        "",
        "Prefer authoritative domains over aggregators. When two sources cover the same story, keep the more authoritative one as Primary, the other as `Also covered by`.",
        "",
        "## Output format (markdown)",
        "A numbered list. For each search:",
        "  - Search query (literal string)",
        "  - Why this query matters",
        "  - Two or three target domains considered authoritative",
        "",
        f"Aim for breadth: by the end of the plan the researcher should be able to retrieve ≥ {min_sources} unique URLs.",
        "If a snippet does not include an explicit date, treat the item as in-window and tag `date: not stated in snippet` rather than discarding it.",
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
        "1. Execute each planned search via DDGS / web tools.",
        "2. From each result extract: title, URL, source domain, publication date if present, and a 3–5 sentence summary.",
        "3. Keep an item even if the snippet does not show an explicit date — tag it `date: not stated in snippet`.",
        "4. Always include the URL with each item. Never invent URLs.",
        "5. **Vendor / regulator cross-check.** When an item names a specific vendor (e.g. Claude, OpenAI, NVIDIA), regulator (e.g. FDA, SEC), or product, run an additional `site:<official-domain>` search using one of the authoritative domains and add the canonical link as `Primary source`. The non-canonical hit becomes `Also covered by`.",
        "6. If a search returns < 3 hits, simplify the query and retry once.",
        "7. Deduplicate by URL before emitting.",
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
    return _join([
        f"# Newsletter Curator — {date_from} → {date_to} (production-grade)",
        "",
        f"Today is **{_today()}**. You are curating a professional newsletter for: {aud}.",
        f"- Industries: {industry_lbl}",
        f"- Sub-domains: {sub_lbl}",
        "",
        "## Source material",
        "Below is the raw Stage-2 collection. It includes (a) per-company news and (b) industry-wide news. Curate it into a tighter, layered list — keep depth. The downstream writer will fill ~50 newsletter sections, so do not over-prune.",
        "",
        "<<RAW_COLLECTION_BEGIN>>",
        raw_collection,
        "<<RAW_COLLECTION_END>>",
        "",
        "## Curation rules",
        "1. **Deduplicate by story, not by URL.** Group items that cover the same event; keep the most authoritative source as `Primary source` and list the rest as `Also covered by`.",
        "2. **Keep volume.** If the raw set has ≥ 30 items, the curated output should retain ≥ 25 of them. Quality over quantity, but volume is required for the final newsletter to be substantive.",
        "3. **Date hygiene.** Prefer items dated within the coverage window. For items tagged `date: not stated in snippet`, include them with that tag preserved.",
        "4. **Drop only obvious noise.** Off-topic items, broken/placeholder URLs, items with no real summary.",
        "5. **Per-item summary** is 3–6 sentences, factual, no marketing language.",
        "6. **Tag categories.** Each item gets a `Category` (Product Launch / Research / Partnership / M&A / Funding / Regulatory / People / Trend / Other).",
        "7. **Highlight 'top stories'.** Tag the 5–8 highest-impact items with `Top: yes`. The writer will lead the newsletter with these.",
        "",
        "## Output format (markdown)",
        "Group items by sub-domain headings. Within each sub-domain, group again by company when applicable. Each item:",
        "",
        "```",
        "### <title>",
        "- **Date**: <YYYY-MM-DD or 'not stated in snippet'>",
        "- **Primary source**: <https://...> (<domain>)",
        "- **Also covered by**: <https://...>, <https://...>  (omit if none)",
        "- **Category**: <one of the categories above>",
        "- **Top**: <yes | no>",
        "- **Summary**: <factual prose>",
        "```",
        "",
        "End with these two sections:",
        "  - `## Coverage Notes` — list any sub-domains that had thin / missing coverage.",
        "  - `## Curation Stats` — total items in raw, total kept, count of `Top: yes`, and a one-line gap analysis.",
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
) -> str:
    aud = audience or "general business / industry stakeholders"
    title_lbl = title or "(auto-generate from industry + sub-domain)"
    seed_lbl = ", ".join(c.get("name", "?") for c in (seed_companies or [])) or "(none — derive from curated set)"

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
        "## Curated material (ground truth)",
        "<<CURATED_BEGIN>>",
        curated,
        "<<CURATED_END>>",
        "",
        "## Your task",
        "1. Identify **5–8 themes** that connect the curated items. For each theme:",
        "   - `Title` (≤ 8 words)",
        "   - `Framing` (one paragraph: what it is, why it matters now, who is affected)",
        "   - `Supporting items` (cite by title + URL, ≥ 3 items)",
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
        "6. Propose the section order for the final newsletter using the canonical section list:",
        "",
        "```",
        *(f"   - {s}" for s in NEWSLETTER_SECTION_LIST),
        "```",
        "",
        "## Output (markdown)",
        "Return a structured outline with the themes, the top/secondary picks, opportunities, risks, deep-dive topic, and the ordered section list. Do not draft the full newsletter yet — that is the writer's job.",
        "",
        "Always produce substantive output. Treat the curated material as authoritative.",
    ])


def generation_writer_prompt(
    *,
    outline: str,
    curated: str,
    industries: List[str],
    sub_domains: List[str],
    date_from: str,
    date_to: str,
    audience: Optional[str],
    title: Optional[str] = None,
    user_urls: Optional[List[str]] = None,
) -> str:
    aud = audience or "general business / industry stakeholders"
    title_lbl = title or f"{', '.join(industries)} — {date_from} to {date_to}"
    user_url_lbl = "\n".join(f"  - {u}" for u in (user_urls or [])) or "  (none)"

    return _join([
        f"# Newsletter Writer — {date_from} → {date_to} (production)",
        "",
        f"Today is **{_today()}**. Draft the **full** professional newsletter for: {aud}.",
        f"- Title: {title_lbl}",
        f"- Industries: {', '.join(industries)}",
        f"- Sub-domains: {', '.join(sub_domains)}",
        "",
        "## Outline (from the analyst)",
        "<<OUTLINE_BEGIN>>",
        outline,
        "<<OUTLINE_END>>",
        "",
        "## Curated source material (ground truth — use these URLs only)",
        "<<CURATED_BEGIN>>",
        curated,
        "<<CURATED_END>>",
        "",
        "## User-supplied URLs (cite these explicitly in the 'Insights from User-Provided Links' section if any)",
        user_url_lbl,
        "",
        "## Drafting rules",
        "- **Length**: long-form. Final document should be **≥ 3500 words**. Do not pad — every sentence should be informative and source-grounded.",
        "- **Structure**: render the canonical **22-section** template below in order. Every numbered section heading must be reproduced **verbatim** (exact text after the number). Do not rename, paraphrase, retitle, append thematic suffixes, drop, reorder, or insert sections. Skip a section only when there is *zero* relevant material — in that case keep the canonical heading and write `_(no in-window material — to monitor next period)_` as the body.",
        "- **Thematic subtitles** (optional): if you want to give a section a thematic title (e.g. naming the focus topic), add it on a separate `### <subtitle>` line **after** the canonical `## N. <Heading>` line. Never fold the thematic title into the canonical heading.",
        "- **Completeness**: emit all 22 numbered sections in a single response. Do not stop before section 22; if you find yourself running long, abbreviate per-section prose rather than truncating the section list.",
        "- **Citations**: every factual claim is followed by an inline link in the form `[<domain>](<url>)`. Use only URLs from the curated set.",
        "- **Per-item depth**: 100–180 words for top stories; 60–120 words for headlines.",
        "- **Tone**: professional, neutral, authoritative. Lead with implication, ground in fact. Avoid superlatives the source does not support.",
        "- **Date discipline**: items whose snippet date was not stated must include `(date: not stated in source snippet)` after their headline.",
        "- **No fabrication**: never invent links, statistics, or quotes. If something is not in the curated set, mark the section as a gap rather than fabricating content.",
        "",
        "## Required structure (markdown — render in this order)",
        "Use a top-level `# <Title>` line, then numbered `##` sections in this exact order:",
        "",
        "  1. `## 1. Newsletter Metadata` — Title / Subtitle / Edition / Date Range / Publication Date / Audience",
        "  2. `## 2. Editor's Note` — 4–6 sentence editorial framing",
        "  3. `## 3. Executive Summary` — 5–8 sentence synthesis (no bullets)",
        "  4. `## 4. TL;DR — Key Takeaways` — 5–8 bullets",
        "  5. `## 5. Industry & Subdomain Focus` — concise scope statement",
        "  6. `## 6. Top Story of the Period` — Summary / Why it matters / Source(s)",
        "  7. `## 7. Secondary Major Story` — Summary / Impact / Source(s)",
        "  8. `## 8. Other Notable Headlines` — bulleted list of 6–12 headlines, each with inline URL",
        "  9. `## 9. Subdomain Highlights` — three sub-sections (`### Highlight #1/#2/#3`), each with Details + Source",
        " 10. `## 10. Releases & Announcements` — sub-sections: Product / Platform Releases · Feature Updates · Research / Whitepapers",
        " 11. `## 11. Trend Intelligence` — sub-sections: Emerging Trends · Declining or Saturating Trends · Market or Ecosystem Signals",
        " 12. `## 12. Audience-Centric Analysis` — sub-sections: What This Means for <audience> · Opportunities · Risks & Challenges",
        " 13. `## 13. Focus Topic Deep Dive` — Background & Context · What Changed in This Date Range · Implications",
        " 14. `## 14. Source-Driven Insights` — Insights from Web Search Sources · Insights from User-Provided Links · Cross-Source Comparison",
        " 15. `## 15. Data & Evidence` — Key Data Points · Statistics Snapshot",
        " 16. `## 16. Quotes & Opinions` — Notable Quotes · Expert Commentary Summary",
        " 17. `## 17. Tools & Resources` — Tools Mentioned · Recommended Reading · Documentation & References",
        " 18. `## 18. Action & Utility` — Recommended Actions · Strategic Considerations · Watchlist Items",
        " 19. `## 19. Forward-Looking Intelligence` — Signals for the Next Period · Predictions (clearly marked as predictive)",
        " 20. `## 20. Transparency & Methodology` — Source Collection Method · Source List · Content Selection Criteria · AI Generation Notes",
        " 21. `## 21. Compliance & Trust` — Bias & Limitations Disclosure · Disclaimer",
        " 22. `## 22. Closure` — Next Edition Preview · Newsletter Footer (industry · sub-domain · date range · 'Generated by AI' · version)",
        "",
        "Output clean markdown only — no commentary, no front-matter notes outside the document itself.",
        "",
        "Always produce substantive content. If a particular sub-section has limited material, summarise what is present and note the gap explicitly.",
    ])


# ──────────────────────────────────────────────────────────────────────────────
# Stage 5: Review (critic → editor → score-card)
# ──────────────────────────────────────────────────────────────────────────────

def review_critic_prompt(
    *,
    draft: str,
    curated: str,
    date_from: str,
    date_to: str,
) -> str:
    return _join([
        f"# Newsletter Critic — {date_from} → {date_to}",
        "",
        f"Today is **{_today()}**. Review the drafted newsletter against the curated source material and produce a corrections list the editor can apply surgically.",
        "",
        "## Draft",
        "<<DRAFT_BEGIN>>",
        draft,
        "<<DRAFT_END>>",
        "",
        "## Curated source material (ground truth)",
        "<<CURATED_BEGIN>>",
        curated,
        "<<CURATED_END>>",
        "",
        "## What to check",
        "1. **Citation integrity** — every URL in the draft appears in the curated set.",
        "2. **Factual fidelity** — claims align with the cited summaries; flag any embellishment, fabrication, or numerical error.",
        "3. **Coverage** — high-impact curated items are not silently omitted. The Top Story should match the analyst's pick and the curated `Top: yes` flags.",
        "4. **Date hygiene** — items with `date: not stated in snippet` carry that note in the draft.",
        "5. **Section completeness** — the 22 top-level sections are present with substantive content (not stubs). Missing sub-sections should be flagged.",
        "6. **Tone** — neutral, no unsupported superlatives, no marketing language.",
        "7. **Length** — draft length is ≥ 3500 words and not padded with filler.",
        "",
        "## Output (markdown)",
        "Return a `## Corrections List` as a numbered list. Each correction:",
        "  - **Where**: section + short quote of the offending sentence",
        "  - **What is wrong**: one of (citation / fact / coverage / date / section / tone / length)",
        "  - **Recommended fix**: the precise change",
        "",
        "End with `## Verdict: pass | needs-revision` and a single-sentence rationale.",
    ])


def review_editor_prompt(
    *,
    draft: str,
    corrections: str,
    curated: str,
    date_from: str,
    date_to: str,
) -> str:
    return _join([
        f"# Newsletter Editor — {date_from} → {date_to} (production)",
        "",
        f"Today is **{_today()}**. Apply the critic's corrections and return the **final** newsletter.",
        "",
        "## Critic's corrections",
        "<<CORRECTIONS_BEGIN>>",
        corrections,
        "<<CORRECTIONS_END>>",
        "",
        "## Draft to revise",
        "<<DRAFT_BEGIN>>",
        draft,
        "<<DRAFT_END>>",
        "",
        "## Curated material (use only these URLs)",
        "<<CURATED_BEGIN>>",
        curated,
        "<<CURATED_END>>",
        "",
        "## Editing rules",
        "- Apply each correction precisely. Do not rewrite the whole document if a surgical edit suffices.",
        "- **Heading discipline (mandatory).** Render every numbered top-level heading **exactly** as the canonical list below. Do not rename, paraphrase, retitle, append thematic suffixes, reorder, drop, or insert sections. If the writer used a non-canonical heading text (e.g. 'Vendor & Platform Landscape' instead of '## 9. Subdomain Highlights'), restore the canonical heading text verbatim and keep the body content under it.",
        "  1. `## 1. Newsletter Metadata`",
        "  2. `## 2. Editor's Note`",
        "  3. `## 3. Executive Summary`",
        "  4. `## 4. TL;DR — Key Takeaways`",
        "  5. `## 5. Industry & Subdomain Focus`",
        "  6. `## 6. Top Story of the Period`",
        "  7. `## 7. Secondary Major Story`",
        "  8. `## 8. Other Notable Headlines`",
        "  9. `## 9. Subdomain Highlights`",
        " 10. `## 10. Releases & Announcements`",
        " 11. `## 11. Trend Intelligence`",
        " 12. `## 12. Audience-Centric Analysis`",
        " 13. `## 13. Focus Topic Deep Dive`",
        " 14. `## 14. Source-Driven Insights`",
        " 15. `## 15. Data & Evidence`",
        " 16. `## 16. Quotes & Opinions`",
        " 17. `## 17. Tools & Resources`",
        " 18. `## 18. Action & Utility`",
        " 19. `## 19. Forward-Looking Intelligence`",
        " 20. `## 20. Transparency & Methodology`",
        " 21. `## 21. Compliance & Trust`",
        " 22. `## 22. Closure`",
        "- If you wish to add a thematic subtitle, place it as a `### <subtitle>` line after the canonical `## N.` heading rather than altering the heading itself.",
        "- All 22 sections must be present in the final output, in this order. If the writer's draft is missing any of them, add the heading and write substantive content drawn from the curated set; if the curated set has nothing applicable, write `_(no in-window material — to monitor next period)_` as the body.",
        "- Every URL must come from the curated set. Strip any URL not present there *and* its surrounding markdown link wrapper, leaving the visible text intact and unmarked.",
        "- Tone is neutral and authoritative. Always produce substantive content; if a section is thin, summarise what is present and add a one-line gap note.",
        "- Output the final newsletter as clean markdown — no commentary, no front-matter notes.",
    ])


def score_card_prompt(
    *,
    final_text: str,
    curated: str,
    date_from: str,
    date_to: str,
    industries: List[str],
    sub_domains: List[str],
    audience: Optional[str] = None,
) -> str:
    """Stage 5 scorecard — produces an authenticity / quality verdict in JSON.

    Output is parsed by ``programmatic_verification.parse_score_card`` and
    surfaced to the UI alongside the final markdown.
    """
    aud = audience or "general business / industry stakeholders"
    return _join([
        f"# Newsletter Score Card — {date_from} → {date_to}",
        "",
        f"Today is **{_today()}**. Score the FINAL newsletter against the curated ground truth.",
        f"Audience: {aud}",
        f"Industries: {', '.join(industries)}",
        f"Sub-domains: {', '.join(sub_domains)}",
        "",
        "## Final newsletter",
        "<<FINAL_BEGIN>>",
        final_text,
        "<<FINAL_END>>",
        "",
        "## Curated ground truth",
        "<<CURATED_BEGIN>>",
        curated,
        "<<CURATED_END>>",
        "",
        "## Scoring rubric (0–100 each)",
        "- **citation_score** — % of factual claims with an inline URL drawn from the curated set",
        "- **factual_fidelity_score** — degree to which claims match the curated summaries (no embellishment, no fabrication)",
        "- **coverage_score** — % of curated `Top: yes` items represented somewhere in the newsletter",
        "- **structural_completeness_score** — % of the 22 top-level sections present with substantive content",
        "",
        "Compute **authenticity_score** as the rounded mean of the four sub-scores above.",
        "",
        "## Verdict bands (use these exact strings)",
        "- ≥ 85 → `production-ready`",
        "- 65–84 → `needs-revision`",
        "- < 65 → `reject`",
        "",
        "## Output — return ONLY a fenced JSON block (```json ... ```) with this exact shape",
        "",
        "```json",
        "{",
        '  "authenticity_score": 0,',
        '  "verdict": "production-ready | needs-revision | reject",',
        '  "citation_score": 0,',
        '  "factual_fidelity_score": 0,',
        '  "coverage_score": 0,',
        '  "structural_completeness_score": 0,',
        '  "suggestions": [',
        '    "Concrete final suggestion #1",',
        '    "Concrete final suggestion #2"',
        '  ],',
        '  "notes": "1–3 sentence overall assessment"',
        "}",
        "```",
        "",
        "Do not return anything outside the fenced JSON block. Be honest — if there are gaps, say so. Suggestions should be actionable (e.g. 'Add the Anthropic enterprise rollout from the curated set to the Top Stories' rather than 'improve coverage').",
    ])
