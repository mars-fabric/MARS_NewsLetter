"""Validate user-supplied links and tag each with an authority tier.

The validator does three things:

1. **Reachability** — issue a HEAD (with GET fallback) and follow redirects.
2. **Domain extraction** — resolve the registrable domain via ``tldextract`` so
   ``docs.aws.amazon.com`` and ``aws.amazon.com`` both classify as ``amazon.com``
   when scoring authority.
3. **Authority classification** — bucket each link as ``official`` (matches one
   of the per-industry authentic-domain hints), ``authority`` (matches the
   neutral-authority list — Reuters, Bloomberg, etc.), or ``unknown``.

Important: an ``unknown`` link is never silently dropped. It is flagged so the
user can confirm or remove it from the UI before Stage 2 advances.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.logging import get_logger

logger = get_logger(__name__)


_TAXONOMY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "industry_taxonomy.json"
_TAXONOMY_CACHE: Optional[dict] = None


def _load_taxonomy() -> dict:
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is None:
        with _TAXONOMY_PATH.open("r", encoding="utf-8") as f:
            _TAXONOMY_CACHE = json.load(f)
    return _TAXONOMY_CACHE


@dataclass
class LinkResult:
    url: str
    reachable: bool = False
    status_code: Optional[int] = None
    final_url: Optional[str] = None
    domain: Optional[str] = None
    is_authentic: bool = False
    authority_tier: str = "unknown"  # official | authority | unknown
    matched_industry: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "reachable": self.reachable,
            "status_code": self.status_code,
            "final_url": self.final_url,
            "domain": self.domain,
            "is_authentic": self.is_authentic,
            "authority_tier": self.authority_tier,
            "matched_industry": self.matched_industry,
            "notes": self.notes,
        }


_HOST_RE = re.compile(r"^[a-z0-9.\-]+$")


def _registrable_domain(url: str) -> Optional[str]:
    """Extract the registrable domain ("amazon.com" from "docs.aws.amazon.com").

    Uses ``tldextract`` when available for proper PSL handling; falls back to a
    simple last-two-labels heuristic when the package is not installed (so the
    smoke-test path still works without optional deps).
    """
    try:
        import tldextract  # type: ignore
        ext = tldextract.extract(url)
        if ext.registered_domain:
            return ext.registered_domain.lower()
        if ext.domain:
            return ext.domain.lower()
    except Exception:
        pass

    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        if not host or not _HOST_RE.match(host):
            return None
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    except Exception:
        return None


def _classify_domain(domain: str, industries: List[str]) -> Tuple[str, bool, Optional[str]]:
    """Return (tier, is_authentic, matched_industry)."""
    if not domain:
        return ("unknown", False, None)

    tax = _load_taxonomy()
    hints: Dict[str, List[str]] = tax.get("authentic_domain_hints", {})
    neutral: List[str] = [d.lower() for d in tax.get("neutral_authority_domains", [])]

    for industry in industries:
        for hint in hints.get(industry, []):
            if domain == hint.lower() or domain.endswith("." + hint.lower()):
                return ("official", True, industry)

    if any(domain == n or domain.endswith("." + n) for n in neutral):
        return ("authority", True, None)

    return ("unknown", False, None)


async def _check_one(client, url: str, industries: List[str]) -> LinkResult:
    import httpx
    result = LinkResult(url=url)
    domain = _registrable_domain(url)
    result.domain = domain
    if domain:
        tier, authentic, matched = _classify_domain(domain, industries)
        result.authority_tier = tier
        result.is_authentic = authentic
        result.matched_industry = matched

    try:
        # HEAD first; some servers reject HEAD, so fall back to GET on 405/403
        try:
            resp = await client.head(url, follow_redirects=True, timeout=10.0)
            if resp.status_code in (403, 405, 501):
                resp = await client.get(url, follow_redirects=True, timeout=10.0)
        except httpx.HTTPError:
            resp = await client.get(url, follow_redirects=True, timeout=10.0)

        result.status_code = resp.status_code
        result.final_url = str(resp.url)
        result.reachable = 200 <= resp.status_code < 400
        if not result.reachable:
            result.notes = f"HTTP {resp.status_code}"
    except httpx.TimeoutException:
        result.notes = "timeout"
    except httpx.HTTPError as exc:
        result.notes = f"network error: {exc.__class__.__name__}"
    except Exception as exc:
        result.notes = f"unexpected: {exc.__class__.__name__}"

    return result


async def validate_links(urls: List[str], industries: List[str]) -> List[LinkResult]:
    """Validate up to ~50 URLs in parallel with a per-host concurrency cap."""
    urls = [u for u in (u.strip() for u in urls) if u]
    if not urls:
        return []

    import httpx
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(headers={"User-Agent": "MARS-NewsLetter/0.1"}, http2=False) as client:
        async def _bound(u: str) -> LinkResult:
            async with sem:
                return await _check_one(client, u, industries)

        results = await asyncio.gather(*(_bound(u) for u in urls), return_exceptions=True)

    out: List[LinkResult] = []
    for u, r in zip(urls, results):
        if isinstance(r, LinkResult):
            out.append(r)
        else:
            out.append(LinkResult(url=u, notes=f"validator error: {r.__class__.__name__}"))
    return out


def summarize_validation(results: List[LinkResult]) -> str:
    """Render a markdown summary of validation results for the work-dir."""
    if not results:
        return "_(no user-supplied URLs)_"

    lines = ["# User-Supplied Links — Validation Report", ""]
    by_tier: Dict[str, List[LinkResult]] = {"official": [], "authority": [], "unknown": []}
    for r in results:
        by_tier.setdefault(r.authority_tier, []).append(r)

    for tier, header in [("official", "## Official / regulator / vendor sources"),
                         ("authority", "## Recognised authoritative press / research"),
                         ("unknown", "## Unknown authority — please verify before use")]:
        items = by_tier.get(tier, [])
        if not items:
            continue
        lines.append(header)
        for r in items:
            ok = "OK" if r.reachable else "UNREACHABLE"
            note = f" — {r.notes}" if r.notes else ""
            ind = f" (matched: {r.matched_industry})" if r.matched_industry else ""
            lines.append(f"- [{ok}] [{r.domain or '?'}]({r.url}) — HTTP {r.status_code or '?'}{ind}{note}")
        lines.append("")

    return "\n".join(lines)
