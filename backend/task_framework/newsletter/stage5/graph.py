"""LangGraph DAG wiring for Stage 5.

Topology (22 nodes):

  load_stage3 ──┐
                ├─► merge_content ─► content_grouping ─► topic_clustering ─► insight_extraction
  load_stage4 ──┘                                                                     │
                                                                                      ▼
                                                                            executive_summary
                                                                                      │
                                                                                      ▼
        ┌──────────────────────── EVALUATION (fan-out / fan-in) ───────────────────────┐
        │                                                                              │
   relevance   diversity   credibility   freshness   redundancy   coverage             │
        └──────────────────────────────── aggregate_score ─────────────────────────────┘
                                                │
                                                ▼
                                         CRITIQUE (sequential)
                                missing_topics → bias → info_loss → improvement
                                                │
                                                ▼
                                   should_regen? ─yes─► section_writer ──┐
                                                │                          │
                                                no                         │
                                                │                          │
                                                └──► report_assembly ◄─────┘
                                                            │
                                                            ▼
                                                  dashboard_metrics ─► visualization_prep
                                                            │
                                                            ▼
                                          markdown_formatter ─► pdf_generator ─► final_output

The conditional ``should_regen`` branch is what makes this a true LangGraph
rather than a linear pipeline: when ``aggregate_score`` finds any high-severity
weak sections, the graph loops back to ``section_writer`` → ``report_assembly``
before producing dashboards/outputs.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .nodes import (
    aggregate_score_node,
    bias_detection_node,
    content_grouping_node,
    coverage_checker_node,
    credibility_scoring_node,
    critic_node,
    dashboard_metrics_node,
    ddgs_research_node,
    diversity_scoring_node,
    editor_node,
    executive_summary_node,
    final_output_node,
    freshness_scoring_node,
    improvement_suggestions_node,
    information_loss_node,
    insight_extraction_node,
    load_stage3_data_node,
    load_stage4_data_node,
    markdown_formatter_node,
    merge_content_node,
    missing_topics_node,
    pdf_generator_node,
    redundancy_detector_node,
    relevance_scoring_node,
    report_assembly_node,
    section_writer_node,
    topic_clustering_node,
    url_verification_node,
    visualization_prep_node,
)
from .state import Stage5State


def _should_regen(state: Stage5State) -> str:
    """Branch: if any high-severity weakness, regenerate before assembly."""
    weak = state.get("weak_sections") or []
    high_sev = [w for w in weak if (w.get("severity") or "").lower() == "high"]
    return "regen" if high_sev else "assemble"


def build_stage5_graph() -> Any:
    """Construct the LangGraph state machine."""
    g = StateGraph(Stage5State)

    # Inputs
    g.add_node("load_stage3", load_stage3_data_node)
    g.add_node("load_stage4", load_stage4_data_node)
    g.add_node("merge_content", merge_content_node)
    g.add_node("url_verification", url_verification_node)

    # Report-building
    g.add_node("content_grouping", content_grouping_node)
    g.add_node("topic_clustering", topic_clustering_node)
    g.add_node("insight_extraction", insight_extraction_node)
    g.add_node("executive_summary", executive_summary_node)

    # Critic / research / editor — the new authenticity loop
    g.add_node("critic", critic_node)
    g.add_node("ddgs_research", ddgs_research_node)
    g.add_node("editor", editor_node)

    # Regeneration + assembly
    g.add_node("section_writer", section_writer_node)
    g.add_node("report_assembly", report_assembly_node)

    # Evaluation — runs AFTER assembly so it scores the cleaned report
    g.add_node("relevance", relevance_scoring_node)
    g.add_node("diversity", diversity_scoring_node)
    g.add_node("credibility", credibility_scoring_node)
    g.add_node("freshness", freshness_scoring_node)
    g.add_node("redundancy", redundancy_detector_node)
    g.add_node("coverage", coverage_checker_node)
    g.add_node("aggregate_score", aggregate_score_node)

    # Self-critique post-assembly
    g.add_node("missing_topics", missing_topics_node)
    g.add_node("bias_detection", bias_detection_node)
    g.add_node("information_loss", information_loss_node)
    g.add_node("improvement_suggestions", improvement_suggestions_node)

    # Dashboard + output
    g.add_node("dashboard_metrics", dashboard_metrics_node)
    g.add_node("visualization_prep", visualization_prep_node)
    g.add_node("markdown_formatter", markdown_formatter_node)
    g.add_node("pdf_generator", pdf_generator_node)
    g.add_node("final_output", final_output_node)

    # Edges — inputs (serialized so node_timings / cost_events don't collide
    # on a parallel reduce; the load nodes are cheap so serialization is fine).
    g.add_edge(START, "load_stage3")
    g.add_edge("load_stage3", "load_stage4")
    g.add_edge("load_stage4", "merge_content")
    g.add_edge("merge_content", "url_verification")

    # Edges — research / critic / editor loop runs BEFORE assembly so the
    # editor's clean markdown drives the assembled report.
    g.add_edge("url_verification", "content_grouping")
    g.add_edge("content_grouping", "topic_clustering")
    g.add_edge("topic_clustering", "insight_extraction")
    g.add_edge("insight_extraction", "executive_summary")
    g.add_edge("executive_summary", "critic")
    g.add_edge("critic", "ddgs_research")
    g.add_edge("ddgs_research", "editor")
    g.add_edge("editor", "report_assembly")

    # Edges — evaluation runs on the assembled (post-edit) report
    g.add_edge("report_assembly", "relevance")
    g.add_edge("relevance", "diversity")
    g.add_edge("diversity", "credibility")
    g.add_edge("credibility", "freshness")
    g.add_edge("freshness", "redundancy")
    g.add_edge("redundancy", "coverage")
    g.add_edge("coverage", "missing_topics")
    g.add_edge("missing_topics", "bias_detection")
    g.add_edge("bias_detection", "information_loss")
    g.add_edge("information_loss", "improvement_suggestions")
    g.add_edge("improvement_suggestions", "aggregate_score")

    # No second assembly pass — section_writer is kept available for future
    # iterations but is now reachable only via direct invocation; the editor
    # handles full-document corrections in a single LLM call.
    g.add_edge("section_writer", "report_assembly")

    # Dashboard + output
    g.add_edge("aggregate_score", "dashboard_metrics")
    g.add_edge("dashboard_metrics", "visualization_prep")
    g.add_edge("visualization_prep", "markdown_formatter")
    g.add_edge("markdown_formatter", "pdf_generator")
    g.add_edge("pdf_generator", "final_output")
    g.add_edge("final_output", END)

    return g.compile()
