"""Tiny service wrapping the industry-taxonomy JSON for the API."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "industry_taxonomy.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def all_industries() -> List[dict]:
    return _data()["industries"]


def authentic_domain_hints() -> Dict[str, List[str]]:
    return _data().get("authentic_domain_hints", {})


def neutral_authority_domains() -> List[str]:
    return _data().get("neutral_authority_domains", [])


def version() -> str:
    return _data().get("version", "0.0.0")


def find_industry(name: str) -> Optional[dict]:
    for entry in all_industries():
        if entry["industry"].lower() == name.lower():
            return entry
    return None


def validate_selection(selections: List[Tuple[str, List[str]]]) -> List[str]:
    """Return a list of validation errors (empty if all good).

    Industries not present in the bundled taxonomy are treated as user-defined
    "custom" industries — we only require they carry at least one sub-domain.
    For taxonomy-listed industries we still enforce that each sub-domain is one
    of the curated entries so spelling errors don't slip through.
    """
    errors: List[str] = []
    if not selections:
        errors.append("At least one industry must be selected.")
        return errors

    for industry, sub_domains in selections:
        if not industry or not industry.strip():
            errors.append("Industry name cannot be empty.")
            continue
        if not sub_domains:
            errors.append(f"At least one sub-domain is required for {industry!r}")
            continue
        entry = find_industry(industry)
        if entry is None:
            # Custom industry — accept any non-empty sub-domain list.
            for sub in sub_domains:
                if not sub or not sub.strip():
                    errors.append(f"Sub-domain entries for {industry!r} cannot be empty.")
                    break
            continue
        valid_subs = {s.lower() for s in entry["sub_domains"]}
        for sub in sub_domains:
            if sub.lower() not in valid_subs:
                errors.append(f"Sub-domain {sub!r} is not part of industry {industry!r}")
    return errors
