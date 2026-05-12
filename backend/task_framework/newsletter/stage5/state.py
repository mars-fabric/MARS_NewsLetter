"""LangGraph state schema for Stage 5 (Report Builder + Evaluator + Dashboard).

The graph passes a single TypedDict around. Nodes read whichever keys they need
and return a partial dict; LangGraph merges the partial back into the state.

Conventions:
  * Inputs to the graph come from the orchestrator and live under ``setup``,
    ``draft``, and ``curated`` — these are immutable for the run.
  * Intermediate analytical artifacts (groups, clusters, scores) live as
    structured dicts on the state; they are NOT serialized to disk unless a
    dedicated output node writes them.
  * Final user-facing artifacts (markdown, score card, dashboard JSON, PDF
    path) sit under the ``output_*`` keys.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


def _merge_dicts(left: Dict[str, Any] | None, right: Dict[str, Any] | None) -> Dict[str, Any]:
    """LangGraph reducer that merges two dicts (right wins on key collision).

    Used for state keys that multiple nodes may write to concurrently (e.g.
    node_timings updates from parallel input nodes).
    """
    out: Dict[str, Any] = dict(left or {})
    out.update(right or {})
    return out


class ContentItem(TypedDict, total=False):
    """One curated article/source, post-Stage-3."""
    title: str
    url: str
    domain: str
    snippet: str
    category: str
    is_top: bool
    published_at: Optional[str]


class TopicCluster(TypedDict, total=False):
    """Output of topic_clustering_node — a group of related items + a theme."""
    cluster_id: str
    theme: str
    items: List[ContentItem]
    section_hint: Optional[str]


class Insight(TypedDict, total=False):
    """Output of insight_extraction_node — one high-signal observation."""
    insight: str
    supporting_urls: List[str]
    confidence: float


class EvaluatorScore(TypedDict, total=False):
    """Output of a single evaluator node. Score is 0-100."""
    score: float
    detail: Dict[str, Any]
    notes: str


class SectionWeakness(TypedDict, total=False):
    """Per-section quality flag produced by coverage/redundancy/etc."""
    section: str
    issue: str
    severity: str  # "low" | "medium" | "high"


class Stage5State(TypedDict, total=False):
    # ── Inputs (immutable) ────────────────────────────────────────────────
    work_dir: str
    setup: Dict[str, Any]
    draft: str          # Stage 4 output: 22-section newsletter markdown
    curated: str        # Stage 3 output: deduplicated curated markdown
    config: Dict[str, Any]

    # ── Parsed / merged inputs ────────────────────────────────────────────
    items: List[ContentItem]            # parsed from curated
    allowed_urls: List[str]             # extracted from curated for verification
    merged_corpus: Dict[str, Any]       # joined view of draft sections + items

    # ── Report-building intermediates ─────────────────────────────────────
    content_groups: Dict[str, List[ContentItem]]   # by category
    clusters: List[TopicCluster]
    insights: List[Insight]
    executive_summary: str
    section_drafts: Dict[str, str]                 # section_id -> markdown
    assembled_report: str                          # markdown of regenerated sections + draft fallback

    # ── Critic / research / editor loop ──────────────────────────────────
    url_verification: Dict[str, Any]               # per-URL reachability report
    critic_corrections: List[Dict[str, Any]]       # critic's structured corrections
    critic_tone_pass: bool
    critic_tone_notes: str
    ddgs_findings: List[Dict[str, Any]]            # web-search backing for high-sev critic items
    edited_markdown: str                           # editor_node output (cleaned full markdown)

    # ── Evaluation ────────────────────────────────────────────────────────
    scores: Dict[str, EvaluatorScore]              # keyed: relevance, diversity, ...
    weak_sections: List[SectionWeakness]
    redundancy_report: Dict[str, Any]
    coverage_report: Dict[str, Any]
    aggregate: Dict[str, Any]                      # overall_score + breakdown

    # ── Self-critique ─────────────────────────────────────────────────────
    missing_topics: List[str]
    bias_findings: List[Dict[str, Any]]
    information_loss: Dict[str, Any]
    improvement_suggestions: List[str]

    # ── Dashboard ─────────────────────────────────────────────────────────
    dashboard_metrics: Dict[str, Any]
    visualization_payload: Dict[str, Any]

    # ── Outputs ───────────────────────────────────────────────────────────
    final_markdown: str
    final_with_score: str
    score_card: Dict[str, Any]
    verification_notes: List[str]
    output_files: List[str]
    pdf_path: Optional[str]
    pdf_backend: Optional[str]
    pdf_error: Optional[str]

    # ── Bookkeeping ───────────────────────────────────────────────────────
    cost_events: List[Dict[str, Any]]
    node_timings: Dict[str, float]
    verification_notes: List[str]
