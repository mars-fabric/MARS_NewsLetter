"""Shared URL reachability check used by Stage 3 (pre-verify the curated
allow-list before the writer can hallucinate from it) and Stage 5
(post-verify the cited URLs for the dashboard).

This single utility keeps the User-Agent / status-code classification rules
identical across stages, so the dashboard's "reachable" number is exactly
what Stage 3 saw when it decided whether to drop a URL from the curated set.

Tier classification:
  * ``ok``      — 2xx / 3xx       → reachable=True
  * ``blocked`` — 401/403/429/451/500/502/503/504
                                  → reachable=True (anti-bot, page exists)
  * ``dead``    — 404/410 + other 4xx
                                  → reachable=False
  * ``error``   — exception (DNS / timeout / TLS / …)
                                  → reachable=False

The "blocked" tier exists because CDN-fronted vendor sites (openai.com,
salesforce.com, azure.microsoft.com, aws.amazon.com) routinely return 403
or 5xx to non-browser clients while serving real users normally. Treating
those as dead generated the 60% false-negative rate that the dashboard
was reporting before this module existed.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List

import httpx

from core.logging import get_logger

logger = get_logger(__name__)


_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Status codes that mean "the page is live, this CDN is just declining to
# serve our probe". Never treat these as dead.
_ANTIBOT_CODES = {401, 403, 429, 451, 500, 502, 503, 504}
# Genuinely-dead status codes for content URLs.
_DEAD_CODES = {404, 410}


def classify_status(code: int | None, error: str | None = None) -> tuple[str, bool]:
    """Return ``(tier, reachable)`` for a status code / error pair."""
    if code is None:
        return "error", False
    if 200 <= code < 400:
        return "ok", True
    if code in _ANTIBOT_CODES:
        return "blocked", True
    if code in _DEAD_CODES:
        return "dead", False
    # Other 4xx (e.g. 400 Bad Request, 422) — treat as dead. 4xx codes the
    # anti-bot allow-list misses are usually a malformed URL the writer
    # invented, which is exactly what we want to catch.
    return "dead", False


async def check_url(client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
    """Single-URL probe — GET (HEAD is unreliable on CDN-fronted sites)."""
    try:
        r = await client.get(url)
        tier, reachable = classify_status(r.status_code)
        return {
            "url": url,
            "status_code": r.status_code,
            "final_url": str(r.url),
            "reachable": reachable,
            "tier": tier,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "url": url,
            "status_code": None,
            "reachable": False,
            "tier": "error",
            "error": str(exc)[:200],
        }


async def check_urls(urls: Iterable[str], *, max_concurrency: int = 16) -> List[Dict[str, Any]]:
    """Concurrently probe every URL with a real-browser UA.

    Returns one result dict per input URL (in the same order). Concurrency is
    capped to keep us friendly to upstream servers while still finishing
    quickly — 30 URLs at concurrency=16 takes ~8 s on typical networks.
    """
    urls = list(urls)
    if not urls:
        return []

    timeout = httpx.Timeout(connect=6.0, read=10.0, write=6.0, pool=10.0)
    sem = asyncio.Semaphore(max_concurrency)

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, headers=_BROWSER_HEADERS, http2=False,
    ) as client:
        async def _bounded(u: str) -> Dict[str, Any]:
            async with sem:
                return await check_url(client, u)

        return await asyncio.gather(*(_bounded(u) for u in urls))


def summarise(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-URL results into the shape Stage 5's dashboard expects."""
    reach = sum(1 for r in results if r.get("reachable"))
    ok = sum(1 for r in results if r.get("tier") == "ok")
    blocked = sum(1 for r in results if r.get("tier") == "blocked")
    dead = sum(1 for r in results if r.get("tier") == "dead")
    errored = sum(1 for r in results if r.get("tier") == "error")
    return {
        "results": results,
        "total": len(results),
        "reachable": reach,
        "dead": dead + errored,
        "ok": ok,
        "blocked": blocked,
        "errored": errored,
        "reachability_pct": round(100.0 * reach / len(results), 1) if results else 100.0,
    }
