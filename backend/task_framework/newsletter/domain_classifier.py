"""Dynamic source-domain tier classifier.

Replaces the "edit ``_DOMAIN_TIER`` every time a new industry is run" pain
point. Resolves a domain to one of ``official | authority | neutral | unknown``
through three layers, in order:

  1. **Static table** (``_DOMAIN_TIER`` in ``stage5/nodes.py``) — manually
     curated, instant, free. Top-tier vendors and regulators live here.

  2. **Deterministic rules** — TLD-based (``.gov``/``.edu``/``.int``/``.mil``
     → ``authority``/``official``) plus subdomain patterns
     (``blog.``/``news.``/``press.``/``investor.``/``about.`` → likely the
     official voice of the parent domain → ``official``). No API call.

  3. **LLM classifier (cached)** — for any domain still unresolved, ask the
     Stage 5 LLM client to classify a batch in one shot, then persist the
     result to ``~/.cache/mars_newsletter/domain_tiers.json`` so the next
     run hits the cache. A domain is only LLM-classified once, ever.

The cache survives across processes and across newsletter runs, so the
first month of usage builds up an organic table that matches whatever
industries the user actually runs.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from core.logging import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Layer 2 — deterministic rules
# ──────────────────────────────────────────────────────────────────────────────

# TLDs that almost always indicate authoritative or official sources.
# ``.gov`` / ``.mil`` / ``.int`` are reserved for governments and
# international bodies; treating them as official is safe. ``.edu`` is more
# nuanced (university press releases are official, student blogs are not),
# but in newsletter contexts an .edu citation is overwhelmingly authority-
# class — papers, research labs, university announcements.
_TRUSTED_TLDS: Dict[str, str] = {
    ".gov": "official",
    ".mil": "official",
    ".int": "official",
    ".edu": "authority",
    ".ac.uk": "authority",
    ".ac.in": "authority",
    ".ac.jp": "authority",
}

# Subdomain prefixes that strongly suggest the host is the parent
# organisation's own voice. ``blog.example.com`` and ``news.example.com``
# are official channels for ``example.com`` by convention. Same with
# ``press.``, ``investor.``, ``newsroom.``, ``about.``, ``about-us.``
# A match here means "the parent domain's tier, or at least neutral".
_OFFICIAL_SUBDOMAIN_PREFIXES: tuple[str, ...] = (
    "blog.", "news.", "press.", "investor.", "investors.",
    "newsroom.", "media.", "about.", "about-us.", "ir.",
    "developer.", "developers.", "engineering.", "research.",
)

# Top-level "industry trade press" indicators baked into domain or path —
# these usually map to ``neutral``: real journalism but not a primary source.
_TRADE_PRESS_HINTS: tuple[str, ...] = (
    "techcrunch", "venturebeat", "theverge", "wired", "arstechnica",
    "infoworld", "zdnet", "cio", "computerworld", "informationweek",
    "techrepublic", "marktechpost", "ieee", "spectrum", "engadget",
)


def classify_deterministic(domain: str) -> Optional[str]:
    """Layer-2 deterministic classifier. Returns None if no rule fires."""
    if not domain:
        return None
    d = domain.lower().lstrip("www.")

    # TLD-based — strongest signal for gov/edu/mil/int hosts.
    for tld, tier in _TRUSTED_TLDS.items():
        if d.endswith(tld):
            return tier

    # Subdomain prefixes that imply "official voice of parent org".
    for prefix in _OFFICIAL_SUBDOMAIN_PREFIXES:
        if d.startswith(prefix):
            return "official"

    # Industry-trade-press hints → neutral (real journalism, not primary).
    for hint in _TRADE_PRESS_HINTS:
        if hint in d:
            return "neutral"

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Layer 3 — LLM classifier (cached on disk)
# ──────────────────────────────────────────────────────────────────────────────

def _cache_path() -> Path:
    """Where the persistent classifier cache lives.

    Default: ``~/.cache/mars_newsletter/domain_tiers.json``. Override with
    ``MARS_DOMAIN_TIER_CACHE`` for tests / multi-tenant deployments.
    """
    override = os.environ.get("MARS_DOMAIN_TIER_CACHE")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    return base / "mars_newsletter" / "domain_tiers.json"


def load_cache() -> Dict[str, str]:
    """Return ``{domain: tier}`` from the on-disk cache.

    Missing or corrupt cache returns an empty dict — never raises.
    """
    p = _cache_path()
    if not p.is_file():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        # Drop any non-string entries defensively.
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("domain_tier_cache_unreadable", path=str(p), error=str(exc))
        return {}


def save_cache(cache: Dict[str, str]) -> None:
    """Persist ``cache`` to disk atomically (write to .tmp + rename)."""
    p = _cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
        tmp.replace(p)
    except OSError as exc:
        logger.warning("domain_tier_cache_unwritable", path=str(p), error=str(exc))


_VALID_TIERS = {"official", "authority", "neutral", "unknown"}


async def classify_via_llm(
    domains: List[str],
    *,
    industries: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Ask the LLM to classify a batch of domains. Returns ``{domain: tier}``.

    Domains are classified by *source role*, not by whether they exist:

      * **official**: domain is a primary source for its content (vendor's
        own blog, official PR, regulator publication, research lab page).
      * **authority**: high-trust independent press / journal / standards
        body (NYT, Nature, IEEE, etc.).
      * **neutral**: legitimate industry-trade press, blog network, etc.
      * **unknown**: SEO content farm, parked domain, unclear provenance.

    Failures fall back to ``unknown`` rather than raising — credibility
    scoring will still apply the reachability bonus and the operator can
    review the cache afterwards.
    """
    if not domains:
        return {}

    from .stage5.llm_client import acomplete_json

    industry_hint = (
        f"\nTarget industry context: {', '.join(industries)}.\n"
        if industries else ""
    )
    schema_hint = (
        '{"<domain>": "official"|"authority"|"neutral"|"unknown", ...}'
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You classify newsletter source domains by editorial role. "
                "Use ONLY these tiers:\n"
                "  - official: the domain is the primary source for what it "
                "publishes (a vendor's own blog/newsroom, a regulator's site, "
                "a research lab's announcements page).\n"
                "  - authority: independent high-trust press, peer-reviewed "
                "journal, standards body, established research institution.\n"
                "  - neutral: legitimate industry-trade press or blog network "
                "that's not a primary source but is a real publication.\n"
                "  - unknown: SEO content farm, parked domain, unclear "
                "provenance, or you genuinely can't tell.\n"
                "Be conservative: when uncertain between official and "
                "authority, prefer authority; between neutral and unknown, "
                "prefer neutral if the domain is recognisably a real outlet."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Classify each of the following domains.{industry_hint}\n"
                "Return ONLY a JSON object mapping each domain to its tier "
                f"(one of the four allowed values). Schema: {schema_hint}\n\n"
                "Domains:\n" + "\n".join(f"  - {d}" for d in domains)
            ),
        },
    ]

    try:
        result, _ = await acomplete_json(
            messages=messages,
            schema_hint=schema_hint,
            temperature=0.0,
            max_tokens=max(400, 30 * len(domains)),
            retries=1,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_domain_classifier_failed", count=len(domains), error=str(exc)[:200])
        return {d: "unknown" for d in domains}

    if not isinstance(result, dict):
        return {d: "unknown" for d in domains}

    cleaned: Dict[str, str] = {}
    for d in domains:
        tier_raw = result.get(d) or result.get(d.lower()) or "unknown"
        tier = str(tier_raw).strip().lower()
        if tier not in _VALID_TIERS:
            tier = "unknown"
        cleaned[d] = tier
    return cleaned


# ──────────────────────────────────────────────────────────────────────────────
# Top-level orchestration
# ──────────────────────────────────────────────────────────────────────────────

async def resolve_domain_tiers(
    domains: Iterable[str],
    *,
    static_table: Dict[str, str],
    industries: Optional[List[str]] = None,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Resolve every domain in ``domains`` to a tier using all three layers.

    Returns ``(tier_map, source_map)`` where ``source_map`` records which
    layer produced each tier (``static`` / ``deterministic`` / ``llm`` /
    ``cache`` / ``default``). Both maps are keyed by the lowercased,
    ``www.``-stripped domain.

    Side effect: the on-disk LLM cache is updated with any newly-classified
    domains so future runs hit the cache.
    """
    tier_map: Dict[str, str] = {}
    source_map: Dict[str, str] = {}
    needs_llm: List[str] = []

    cache = load_cache()

    seen: set[str] = set()
    for raw in domains:
        if not raw:
            continue
        d = raw.lower().lstrip("www.")
        if d in seen:
            continue
        seen.add(d)

        # Layer 1: static table.
        t = static_table.get(d) or static_table.get(d.split(".", 1)[-1])
        if t:
            tier_map[d] = t
            source_map[d] = "static"
            continue

        # Layer 2: deterministic rules.
        t = classify_deterministic(d)
        if t:
            tier_map[d] = t
            source_map[d] = "deterministic"
            continue

        # Layer 3a: persistent LLM cache from previous runs.
        if d in cache:
            tier_map[d] = cache[d]
            source_map[d] = "cache"
            continue

        # Layer 3b: defer to a batched LLM call.
        needs_llm.append(d)

    if needs_llm:
        logger.info("domain_classifier_llm_batch", domains=needs_llm[:20], count=len(needs_llm))
        started = time.time()
        llm_results = await classify_via_llm(needs_llm, industries=industries)
        logger.info(
            "domain_classifier_llm_done",
            count=len(llm_results),
            duration_s=round(time.time() - started, 2),
        )
        for d, tier in llm_results.items():
            tier_map[d] = tier
            source_map[d] = "llm"
            # Always cache, even the unknowns — saves us from re-asking next time.
            cache[d] = tier
        save_cache(cache)

    return tier_map, source_map
