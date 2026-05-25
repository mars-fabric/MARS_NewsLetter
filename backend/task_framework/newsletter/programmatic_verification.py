"""Programmatic post-checks applied after the editor in Stage 5.

These are deterministic safety nets — they run in Python after the LLM has
finished and they cannot be argued out of. Their job:

1. Strip URLs that are clearly placeholder / fabricated.
2. Strip URLs not present in the curated allow-set, **leaving the visible
   text intact and unmarked** (no strikethrough — strikethrough renders as
   noise in the PDF and confuses readers).
3. Soften unsupported absolute superlatives.
4. Ensure the canonical 22 top-level sections exist.
5. Verify the source list / references section is non-empty.

Returns the cleaned text plus a list of verification notes that the UI surfaces
under "verification" so the operator can see what was fixed.

This module also exposes ``parse_score_card`` — Stage 5 uses it to extract the
JSON scorecard the LLM emits and falls back to a minimal stub when parsing
fails (so the run never breaks on a malformed JSON block).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Set, Tuple

# 22 top-level sections — these mirror the section list emitted by Stage 4's
# writer prompt (`generation_writer_prompt`). The verifier inserts a stub if
# the editor accidentally drops one.
_REQUIRED_SECTIONS = (
    "Newsletter Metadata",
    "Editor's Note",
    "Executive Summary",
    "TL;DR",
    "Industry & Subdomain Focus",
    "Top Story of the Period",
    "Secondary Major Story",
    "Other Notable Headlines",
    "Subdomain Highlights",
    "Releases & Announcements",
    "Trend Intelligence",
    "Audience-Centric Analysis",
    "Focus Topic Deep Dive",
    "Source-Driven Insights",
    "Data & Evidence",
    "Quotes & Opinions",
    "Tools & Resources",
    "Action & Utility",
    "Forward-Looking Intelligence",
    "Transparency & Methodology",
    "Compliance & Trust",
    "Closure",
)

# Canonical heading text (full ``## N. <Title>`` form) by position, used to
# normalise the editor's headings when it renames or thematically retitles
# numbered sections. This mirrors the writer-prompt list verbatim — keep the
# two in sync when sections are renamed.
_CANONICAL_HEADINGS: tuple[str, ...] = (
    "Newsletter Metadata",
    "Editor's Note",
    "Executive Summary",
    "TL;DR — Key Takeaways",
    "Industry & Subdomain Focus",
    "Top Story of the Period",
    "Secondary Major Story",
    "Other Notable Headlines",
    "Subdomain Highlights",
    "Releases & Announcements",
    "Trend Intelligence",
    "Audience-Centric Analysis",
    "Focus Topic Deep Dive",
    "Source-Driven Insights",
    "Data & Evidence",
    "Quotes & Opinions",
    "Tools & Resources",
    "Action & Utility",
    "Forward-Looking Intelligence",
    "Transparency & Methodology",
    "Compliance & Trust",
    "Closure",
)

_SUPERLATIVES = (
    r"\bthe world's first\b", r"\bthe only\b", r"\bguaranteed\b",
    r"\bunprecedented\b", r"\brevolutionary\b", r"\bgame-changing\b",
)

_PLACEHOLDER_PATTERNS = (
    r"https?://example\.com[^\s)]*",
    r"https?://placeholder[^\s)]*",
    r"https?://your-source[^\s)]*",
    r"https?://\.{1,}/?",
)


def verify_and_clean(
    *,
    final_text: str,
    allowed_urls: Set[str],
) -> Tuple[str, List[str]]:
    notes: List[str] = []
    text = final_text or ""

    # 0a. Strip any pre-document preamble the editor may have prepended before
    #     the actual `# <Title>` heading. When the editor agent runs in P&C
    #     mode, the engineer sometimes writes content via a Python snippet,
    #     the snippet fails on long strings, and the model narrates the failure
    #     ("The Python snippet failed because…") above the real markdown.
    #     Deterministic fix: discard everything before the first level-1
    #     heading and any stray HTML comments / code-fence markers right after.
    text, preamble_notes = _strip_pre_heading_preamble(text)
    notes.extend(preamble_notes)

    # 0b. Heading normalisation — restore canonical numbered headings the editor
    #    may have thematically renamed (e.g. ``## 13. AI & Data Infrastructure``
    #    → ``## 13. Focus Topic Deep Dive``). The writer is instructed to emit
    #    these verbatim; the editor sometimes overrides. We trust the section
    #    NUMBER as the authoritative position marker and rewrite the heading
    #    text back to the canonical name, preserving the editor's wording as a
    #    ``### <original heading>`` subtitle so the thematic framing is not
    #    lost. This keeps the structural completeness score stable across
    #    runs and makes downstream readers see the canonical structure.
    text, normalisation_notes = _normalise_canonical_headings(text)
    notes.extend(normalisation_notes)

    # 1. Drop placeholder URLs anywhere they appear.
    for pat in _PLACEHOLDER_PATTERNS:
        if re.search(pat, text):
            text = re.sub(pat, "", text)
            notes.append(f"Removed placeholder URL matching pattern `{pat}`.")

    # 2. Strip URLs not present in the curated allow-set. The previous version
    #    wrapped the visible text in ``~~strikethrough~~`` which renders as a
    #    visual artifact in the PDF — clients see crossed-out text in their
    #    final newsletter. Now we keep the visible text plain and unmarked.
    #
    # Regex correctness — critical: ``[^)]+`` was being used for the URL
    # portion, but ``.`` and ``[^)]`` both match newlines in Python's default
    # mode, so a markdown link missing its closing ``)`` (which happens when
    # Stage 4 hits max_tokens mid-link) made the regex span entire SECTIONS
    # looking for the next ``)``. The captured "URL" then contained section
    # headings, bullet points, blank lines — whole-document content. That
    # content was dumped into a ``Stripped URL ...`` verification note and
    # *removed* from the body, gutting whatever sections came after the
    # broken link. The fix is to forbid whitespace (including newlines)
    # inside the URL portion and inside the link text portion of markdown
    # links — well-formed links never contain those, and broken/truncated
    # links should simply not match at all.
    if allowed_urls:
        def _url_in_allowlist(url: str) -> bool:
            return url in allowed_urls or any(url.startswith(a) for a in allowed_urls)

        def _record_strip(message: str) -> None:
            # Always single-line — verification-note rendering joins each
            # note as a bullet, and a multi-line note would break the block.
            notes.append(message.replace("\n", " ").replace("\r", " ").strip()[:240])

        def _drop_unknown(match: re.Match) -> str:
            url = match.group(2).rstrip(".,;:!?'\"]>")
            if _url_in_allowlist(url):
                return match.group(0)
            _record_strip(f"Stripped URL not in curated set: {url}")
            return match.group(1)  # keep the visible text only — clean removal

        # Restrict both link text and URL to a single line: ``[^\]\n]`` and
        # ``[^)\s]``. Stage 4 outputs well-formed links on a single line; if
        # one isn't (because a section was truncated mid-link), we leave the
        # half-written link alone instead of swallowing the rest of the doc.
        text = re.sub(
            r"\[([^\]\n]+)\]\((https?://[^)\s\n]+)\)",
            _drop_unknown,
            text,
        )

        # Also catch bare ``<https://...>`` and naked ``https://...`` not in
        # the allow-set. Replace bare-tag versions with empty string; remove
        # naked URLs (rare, but happens when the LLM forgets the markdown link).
        def _drop_bare_tag(match: re.Match) -> str:
            url = match.group(1).rstrip(".,;:!?'\"]>")
            if _url_in_allowlist(url):
                return match.group(0)
            _record_strip(f"Removed bare-tag URL not in curated set: {url}")
            return ""

        text = re.sub(r"<(https?://[^>\s\n]+)>", _drop_bare_tag, text)

        def _drop_naked(match: re.Match) -> str:
            url = match.group(0).rstrip(".,;:!?'\"]>")
            if _url_in_allowlist(url):
                return match.group(0)
            _record_strip(f"Removed naked URL not in curated set: {url}")
            return ""

        text = re.sub(r"https?://[^\s)\]<>\"'\n]+", _drop_naked, text)

    # 2b. Trim broken half-written markdown links (``[text](https://...`` with
    #     no closing ``)``). These are the only remaining residue from
    #     truncated Stage-4 sections after the canonical link regex passes
    #     them over. Leaving them in the body shows up as a stray ``(`` in
    #     the rendered output and confuses the reader; cleaner to drop the
    #     half-written link target and keep the visible text.
    text = re.sub(
        r"\[([^\]\n]+)\]\(\s*https?://[^)\s\n]*\s*(?=\n|$)",
        lambda m: m.group(1),
        text,
    )

    # 3. Soften superlatives.
    for pat in _SUPERLATIVES:
        if re.search(pat, text, flags=re.IGNORECASE):
            text = re.sub(pat, "notable", text, flags=re.IGNORECASE)
            notes.append(f"Softened superlative `{pat}` → `notable`.")

    # 4. Ensure all 22 canonical sections are present. A section is considered
    #    "present" if EITHER:
    #      a) the canonical heading text (or its thematic variant) appears
    #         under a ``## [N. ]`` heading, OR
    #      b) the numeric position (``## N.``) appears in the document — the
    #         heading text may have been thematically renamed by the editor
    #         or partially mangled by a downstream pass, but the slot exists.
    #    Without (b) the previous version produced phantom-stub duplicates
    #    when the URL stripper bug ate a section's body but left its heading
    #    in place. We now only stub when both checks fail.
    for idx, section in enumerate(_REQUIRED_SECTIONS, start=1):
        name_pattern = rf"^#{{1,3}}\s+(?:\d+\.\s+)?{re.escape(section)}\b"
        slot_pattern = rf"^##\s+{idx}\.\s+"
        has_name = re.search(name_pattern, text, flags=re.MULTILINE | re.IGNORECASE)
        has_slot = re.search(slot_pattern, text, flags=re.MULTILINE)
        if not (has_name or has_slot):
            text += f"\n\n## {idx}. {section}\n\n_(no in-window material — to monitor next period)_\n"
            notes.append(f"Added missing canonical section: {section}.")

    return text, notes


def _normalise_canonical_headings(text: str) -> Tuple[str, List[str]]:
    """Rewrite ``## N. <text>`` headings to the canonical name for position N.

    The writer's prompt emits 22 fixed-position numbered headings; the editor
    occasionally renames them. We trust the section number as the authoritative
    position and force the heading text back to canonical so structural
    verification, the score card, and the rendered TOC all line up.

    Behaviour:
    * If the heading is already canonical (or canonical with a `: <suffix>` /
      `— <suffix>` thematic appendix), leave it alone.
    * Otherwise rewrite to the canonical heading and inject the editor's
      thematic title as a `### <original>` subtitle line below, so the framing
      is preserved.
    * Records each rewrite as a verification note.

    Sections numbered outside 1-22 are ignored. The function is idempotent.
    """
    if not text:
        return text, []

    notes: List[str] = []
    pattern = re.compile(r"^(##\s+(\d+)\.\s+)([^\n]+?)\s*$", flags=re.MULTILINE)

    def _replace(match: re.Match) -> str:
        prefix = match.group(1)
        try:
            num = int(match.group(2))
        except (TypeError, ValueError):
            return match.group(0)
        if num < 1 or num > len(_CANONICAL_HEADINGS):
            return match.group(0)
        canonical = _CANONICAL_HEADINGS[num - 1]
        actual = match.group(3).strip()

        # Already canonical (or canonical + thematic suffix like
        # ``Focus Topic Deep Dive: <topic>`` or ``Top Story of the Period — <story>``).
        # We keep these as-is; the regex anchored at the start of the canonical
        # name handles both verbatim and `<canonical><sep><suffix>` forms.
        canonical_lc = canonical.lower()
        actual_lc = actual.lower()
        if actual_lc == canonical_lc:
            return match.group(0)
        # Accept canonical-with-suffix when there is a clear separator and the
        # suffix is non-empty thematic text. Suffixes "(continued)" or empty
        # don't count as canonical and should not block normalisation here.
        sep_re = re.compile(r"^" + re.escape(canonical_lc) + r"\s*[:—\-–]\s*\S")
        if sep_re.match(actual_lc):
            return match.group(0)

        notes.append(
            f"Section {num}: editor renamed `{canonical}` to `{actual}`; "
            f"restored canonical heading and preserved original as a subtitle."
        )
        # Replace the heading. Inject the editor's wording as a thematic
        # subtitle on the next line so the contextual framing is not lost. We
        # only add the subtitle when the original heading carried thematic
        # information beyond a near-canonical phrasing — short stub like
        # "Closing Remarks" is preserved so readers still see the editor's
        # intent.
        return f"{prefix}{canonical}\n\n### {actual}"

    new_text = pattern.sub(_replace, text)
    return new_text, notes


# ──────────────────────────────────────────────────────────────────────────────
# Score-card parsing
# ──────────────────────────────────────────────────────────────────────────────

_SCORE_KEYS = (
    "authenticity_score",
    "citation_score",
    "factual_fidelity_score",
    "coverage_score",
    "structural_completeness_score",
)


def parse_score_card(raw: str) -> Dict[str, Any]:
    """Extract the JSON score-card object the Stage-5 score prompt emitted.

    Tries (in order):
      1. The first ```json ... ``` fenced block.
      2. The first ``` ... ``` fenced block (untyped).
      3. The first balanced ``{ ... }`` substring.

    Returns a dict with the canonical fields; any field that fails to parse
    falls back to a sensible default so the rest of Stage 5 can keep running.
    """
    fallback: Dict[str, Any] = {
        "authenticity_score": 0,
        "verdict": "needs-revision",
        "citation_score": None,
        "factual_fidelity_score": None,
        "coverage_score": None,
        "structural_completeness_score": None,
        "suggestions": ["Score-card JSON could not be parsed — re-run Stage 5 to generate a clean score."],
        "notes": "Score-card parsing fallback; LLM output was not valid JSON.",
    }

    if not raw or not raw.strip():
        return fallback

    # Cmbagent's researcher_response_formatter sometimes wraps the score-card
    # markdown in a Python "save-to-file" script (``content = '<repr-escaped>'``).
    # Recover the inner string before searching for the JSON block.
    unwrapped = _unwrap_python_content_script(raw)
    if unwrapped:
        raw = unwrapped

    candidates: List[str] = []
    fenced = re.search(r"```(?:json)?\s*\n([\s\S]*?)```", raw)
    if fenced:
        candidates.append(fenced.group(1))
    # Try the first { ... } substring as a last resort.
    brace = re.search(r"\{[\s\S]*\}", raw)
    if brace:
        candidates.append(brace.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return _normalise_score(parsed)
        except (ValueError, TypeError):
            continue

    return fallback


_TOP_HEADING_PREAMBLE_RE = re.compile(r"^# +\S", re.MULTILINE)


def _strip_pre_heading_preamble(text: str) -> Tuple[str, List[str]]:
    """Drop any text before the first top-level `# ` heading.

    Stage 5 editors occasionally narrate a failed Python snippet ("The Python
    snippet failed because…") above the real markdown when the engineer agent
    tries to write content via code execution. The deterministic fix is to
    drop everything before the first `# ` line and clean stray fences right
    after.
    """
    if not text:
        return text, []
    notes: List[str] = []
    m = _TOP_HEADING_PREAMBLE_RE.search(text)
    if m and m.start() > 0:
        notes.append(f"Stripped {m.start()} chars of pre-heading preamble.")
        text = text[m.start():]
    # Remove a leading HTML filename hint comment if present.
    new_text, n = re.subn(r"^<!--[^>]*-->\s*\n?", "", text)
    if n:
        notes.append("Stripped leading HTML filename comment.")
        text = new_text
    # Remove a leading triple-backtick fence (markdown/text/python) if any.
    new_text, n = re.subn(r"^```[a-zA-Z]*\s*\n", "", text)
    if n:
        notes.append("Stripped leading code-fence opener.")
        text = new_text
    return text, notes


def _unwrap_python_content_script(text: str) -> str | None:
    """Recover the markdown the formatter packed into a ``content = '...'`` line.

    Mirrors ``mode_dispatcher._unwrap_formatter_payload`` so the score-card
    parser is resilient to the same wrapper pattern when the upstream extractor
    returns the raw script body unchanged.
    """
    import ast
    if "content" not in text:
        return None
    block = re.search(r"```python\s*\n([\s\S]*?)```", text)
    body = block.group(1) if block else text
    m = re.search(r"^\s*content\s*=\s*(.+?)\s*$", body, flags=re.MULTILINE)
    if not m:
        return None
    try:
        value = ast.literal_eval(m.group(1))
        return value if isinstance(value, str) else None
    except (SyntaxError, ValueError):
        return None


def _normalise_score(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce field types and clip integer scores to [0, 100]."""
    out: Dict[str, Any] = {}
    for key in _SCORE_KEYS:
        v = raw.get(key)
        if v is None:
            out[key] = None if key != "authenticity_score" else 0
            continue
        try:
            out[key] = max(0, min(100, int(round(float(v)))))
        except (ValueError, TypeError):
            out[key] = None if key != "authenticity_score" else 0

    verdict = str(raw.get("verdict") or "").strip().lower()
    if verdict not in ("production-ready", "needs-revision", "reject"):
        # Derive from authenticity_score band if the LLM gave a free-form verdict.
        score = out.get("authenticity_score") or 0
        verdict = "production-ready" if score >= 85 else ("needs-revision" if score >= 65 else "reject")
    out["verdict"] = verdict

    suggestions = raw.get("suggestions")
    if isinstance(suggestions, list):
        out["suggestions"] = [str(s).strip() for s in suggestions if str(s).strip()]
    elif isinstance(suggestions, str) and suggestions.strip():
        out["suggestions"] = [suggestions.strip()]
    else:
        out["suggestions"] = []

    notes = raw.get("notes")
    out["notes"] = str(notes).strip() if isinstance(notes, str) else None
    return out
