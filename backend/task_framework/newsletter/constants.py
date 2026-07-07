"""Single source of truth for cross-stage newsletter constants.

Currently exports:
  * ``CANONICAL_HEADINGS`` — the 22 top-level section names, in order.

Every module that needs to *identify*, *validate*, or *normalise* newsletter
sections imports from here so that renaming a section touches exactly one file.

The per-section drafting guidance (word budgets, sub-section shape) still lives
alongside the Stage-4 writer in :mod:`.stage4.sections`, because that guidance
is only meaningful to the writer. This file keeps the *names*.
"""

from __future__ import annotations

from typing import Tuple

# Canonical 22 top-level section names, in position order.
#
# Position N in this tuple corresponds to the ``## N. <heading>`` heading the
# writer must emit. Substring-match against a heading line is the standard
# containment check (see ``programmatic_verification.verify_and_clean`` and
# ``stage5.nodes.coverage_checker_node``); the full "TL;DR — Key Takeaways"
# form is used because that's what the writer emits and it also contains the
# shorter "TL;DR" — the reverse containment does not hold.
CANONICAL_HEADINGS: Tuple[str, ...] = (
    "Newsletter Metadata",
    "Editor's Note",
    "Executive Summary",
    "TL;DR",  # matches "TL;DR" and "TL;DR — Key Takeaways" alike
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

assert len(CANONICAL_HEADINGS) == 22, "Newsletter is defined as a 22-section document."
