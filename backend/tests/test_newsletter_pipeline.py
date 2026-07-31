"""Deterministic unit tests for the NewsLetter Stage-4 → Stage-5 refactor.

Covers the pieces changed in the 2026-07-28 refactor without touching the
network or an LLM:

  * markdown → structured JSON parsing (headings / subsections / links)
  * link extraction + trailing-punctuation normalisation
  * strict URL-set enhancement guard (the link-corruption fix)
  * presentation HTML render (cards, TOC, sources, broken-link handling)
  * env-driven per-stage mode resolution (per-stage UI removed)
  * env-driven Stage-2 knobs when mode_config is absent

Run: ``pytest tests/test_newsletter_pipeline.py -q`` from ``backend/``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.newsletter_schemas import CmbAgentMode  # noqa: E402
from task_framework.newsletter.stage5_report.markdown_parser import (  # noqa: E402
    extract_links,
    nest_sections,
    parse_markdown,
)
from task_framework.newsletter.stage5_report.html_renderer import (  # noqa: E402
    document_to_markdown,
    render_html,
)
from task_framework.newsletter.stage5_report import nodes as s5nodes  # noqa: E402
from task_framework.newsletter import helpers as nl_helpers  # noqa: E402


SAMPLE_MD = """# GenAI Weekly

_Coverage: 2026-07-21 → 2026-07-28_

## 1. Executive Summary

Frontier models advanced this week.[moonshot.ai](https://www.moonshot.ai/) A second
claim follows.[anthropic.com](https://www.anthropic.com/news)

## 2. Key Trends

Trend body with a bare link https://example.com/report and a
markdown one.[nvidia](https://nvidianews.nvidia.com/news/x)

### 2a. Sub-trend

A nested subsection.[hf](https://huggingface.co/blog/y)
"""


# ──────────────────────────────────────────────────────────────────────────────
# 1. markdown → JSON parsing
# ──────────────────────────────────────────────────────────────────────────────

def test_parse_markdown_extracts_title_and_sections():
    title, subtitle, flat = parse_markdown(SAMPLE_MD)
    assert title == "GenAI Weekly"
    assert "Coverage" in subtitle
    headings = [s["title"] for s in flat]
    assert "1. Executive Summary" in headings
    assert "2. Key Trends" in headings
    assert "2a. Sub-trend" in headings


def test_nest_sections_folds_subsection_under_parent():
    _, _, flat = parse_markdown(SAMPLE_MD)
    roots = nest_sections(flat)
    # Two top-level (## ) sections; the ### sub-trend nests under Key Trends.
    assert len(roots) == 2
    key_trends = next(s for s in roots if s["title"].startswith("2."))
    assert len(key_trends["subsections"]) == 1
    assert key_trends["subsections"][0]["title"] == "2a. Sub-trend"


def test_extract_links_handles_markdown_and_bare_and_dedupes():
    links = extract_links(
        "See [a](https://x.com/p) and https://x.com/p again, plus [b](https://y.com/q)."
    )
    urls = sorted(l["url"] for l in links)
    # https://x.com/p appears twice (markdown + bare) → deduped to one.
    assert urls == ["https://x.com/p", "https://y.com/q"]


def test_extract_links_strips_trailing_punctuation():
    links = extract_links("End of sentence.[src](https://z.com/a).")
    assert links[0]["url"] == "https://z.com/a"  # trailing ')' + '.' removed


# ──────────────────────────────────────────────────────────────────────────────
# 2. strict URL-set enhancement guard (link-corruption fix)
# ──────────────────────────────────────────────────────────────────────────────

def test_url_set_normalises_trailing_punctuation():
    a = s5nodes._url_set([{"url": "https://a.com/x"}, {"url": "https://b.com/y."}])
    assert a == {"https://a.com/x", "https://b.com/y"}


def test_enhance_rejects_url_swap(monkeypatch):
    """If the LLM keeps the link count but swaps a URL, the rewrite is rejected."""
    section = {
        "id": "s1",
        "title": "Test",
        "content": "Claim one.[a](https://real.com/a) Claim two.[b](https://real.com/b) "
        + "padding " * 30,
        "links": [{"text": "a", "url": "https://real.com/a"}, {"text": "b", "url": "https://real.com/b"}],
    }

    async def fake_acomplete(**kwargs):
        # Same count, but one URL corrupted → must be rejected.
        return ("Better prose.[a](https://real.com/a) Two.[b](https://EVIL.com/b)", {})

    monkeypatch.setattr(s5nodes, "acomplete", fake_acomplete)
    asyncio.run(s5nodes._enhance_one(section, model="x", cost_cb=lambda p: None))
    # Original content preserved because the URL set changed.
    assert "EVIL.com" not in section["content"]
    assert "real.com/b" in section["content"]


def test_enhance_accepts_identical_url_set(monkeypatch):
    section = {
        "id": "s1",
        "title": "Test",
        "content": "Old prose.[a](https://real.com/a) more.[b](https://real.com/b) " + "pad " * 30,
        "links": [{"text": "a", "url": "https://real.com/a"}, {"text": "b", "url": "https://real.com/b"}],
    }

    async def fake_acomplete(**kwargs):
        return ("New sharper prose.[a](https://real.com/a) more.[b](https://real.com/b)", {})

    monkeypatch.setattr(s5nodes, "acomplete", fake_acomplete)
    asyncio.run(s5nodes._enhance_one(section, model="x", cost_cb=lambda p: None))
    assert section["content"].startswith("New sharper prose")


# ──────────────────────────────────────────────────────────────────────────────
# 3. presentation render
# ──────────────────────────────────────────────────────────────────────────────

def _sample_doc():
    _, _, flat = parse_markdown(SAMPLE_MD)
    return {
        "title": "GenAI Weekly",
        "subtitle": "Coverage: 2026-07-21 → 2026-07-28",
        "meta": {"coverage": "2026-07-21 → 2026-07-28", "audience": "CTOs", "generated_at": "2026-07-28"},
        "sections": nest_sections(flat),
    }


def test_render_html_produces_cards_toc_and_valid_shell():
    html = render_html(_sample_doc())
    assert html.startswith("<!DOCTYPE html>")
    assert 'class="card"' in html
    assert 'class="toc"' in html
    assert "card-num" in html  # numbered pill
    # Every real link becomes a target=_blank anchor.
    assert 'href="https://www.moonshot.ai/"' in html


def test_render_html_marks_broken_links_inert():
    doc = _sample_doc()
    # Flag one link broken.
    for sec in doc["sections"]:
        for l in sec.get("links", []):
            l["ok"] = False
            break
        break
    html = render_html(doc)
    assert "broken-link" in html


def test_document_to_markdown_roundtrips_sources():
    md = document_to_markdown(_sample_doc())
    assert md.startswith("# GenAI Weekly")
    assert "**Sources:**" in md
    assert "https://www.moonshot.ai/" in md


# ──────────────────────────────────────────────────────────────────────────────
# 4. env-driven stage config (per-stage UI removed)
# ──────────────────────────────────────────────────────────────────────────────

def test_stage_mode_defaults_to_one_shot(monkeypatch):
    monkeypatch.delenv("NEWSLETTER_DEFAULT_MODE", raising=False)
    monkeypatch.delenv("NEWSLETTER_STAGE_4_MODE", raising=False)
    assert nl_helpers._stage_mode({}, 4, None) == CmbAgentMode.ONE_SHOT


def test_stage_mode_reads_stage_specific_env(monkeypatch):
    monkeypatch.setenv("NEWSLETTER_STAGE_4_MODE", "planning_and_control")
    assert nl_helpers._stage_mode({}, 4, None) == CmbAgentMode.PLANNING_AND_CONTROL


def test_stage_mode_default_env_applies_to_all(monkeypatch):
    monkeypatch.delenv("NEWSLETTER_STAGE_3_MODE", raising=False)
    monkeypatch.setenv("NEWSLETTER_DEFAULT_MODE", "deep_research")
    assert nl_helpers._stage_mode({}, 3, None) == CmbAgentMode.DEEP_RESEARCH


def test_stage_mode_override_wins(monkeypatch):
    monkeypatch.setenv("NEWSLETTER_DEFAULT_MODE", "deep_research")
    assert nl_helpers._stage_mode({}, 2, CmbAgentMode.ONE_SHOT) == CmbAgentMode.ONE_SHOT


def test_stage_mode_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("NEWSLETTER_STAGE_4_MODE", "not_a_mode")
    monkeypatch.delenv("NEWSLETTER_DEFAULT_MODE", raising=False)
    assert nl_helpers._stage_mode({}, 4, None) == CmbAgentMode.ONE_SHOT


def test_env_int_and_flag_helpers(monkeypatch):
    monkeypatch.setenv("NL_TEST_INT", "42")
    monkeypatch.setenv("NL_TEST_FLAG", "yes")
    assert nl_helpers._env_int("NL_TEST_INT", 0) == 42
    assert nl_helpers._env_int("NL_MISSING_INT", 7) == 7
    assert nl_helpers._env_flag("NL_TEST_FLAG", False) is True
    assert nl_helpers._env_flag("NL_MISSING_FLAG", True) is True
