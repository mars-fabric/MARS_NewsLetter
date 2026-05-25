"""Stage 4 — section-by-section newsletter writer (long-document mode).

Why this exists
---------------
The legacy ``helpers.run_stage_4`` dispatches *one* cmbagent
``planning_and_control_context_carryover`` call to draft the entire 22-section
newsletter. That call is subject to cmbagent's per-message content cap
(25 000 chars by default) which causes the "content truncated: N → M chars"
banner to leak into the final report on rich inputs.

PaperPulse solves the same problem by writing each section of its paper as a
separate LangGraph node that reads the accumulated prior sections from
GraphState rather than from cmbagent's message history. Each call is small,
no per-message cap is ever crossed, and the final document is assembled in
plain Python.

This package ports that pattern to the newsletter: the analyst outline is
still produced by cmbagent (small output), then a Python loop drafts the 22
canonical sections one at a time via the litellm-based ``acomplete`` client
used by Stage 5. Each section prompt sees the outline, the curated allow-list,
and a short tail of the already-written draft for continuity — no global
cmbagent message history, no truncation.
"""

from .runner import run_stage_4_sectioned

__all__ = ["run_stage_4_sectioned"]
