"""LangGraph wiring for the Stage-5 dynamic report builder.

Linear DAG (each node is defensive so the pipeline always reaches ``render``):

    parse ─► validate_links ─► link_fix ─► render ─► END

The LLM ``enhance`` node was removed: the LLM polish pass corrupted link URLs
even when the strict URL-set equality guard was in place (LLM reordered or
paraphrased anchor text while swapping URLs). The deterministic ``link_fix``
node replaces it: it finds links flagged as broken by the validation pass and
removes the dead href, keeping the visible text intact.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import link_fix_node, parse_node, render_node, validate_links_node
from .state import Stage5ReportState

_GRAPH = None


def build_report_graph():
    graph = StateGraph(Stage5ReportState)
    graph.add_node("parse", parse_node)
    graph.add_node("validate_links", validate_links_node)
    graph.add_node("link_fix", link_fix_node)
    graph.add_node("render", render_node)

    graph.add_edge(START, "parse")
    graph.add_edge("parse", "validate_links")
    graph.add_edge("validate_links", "link_fix")
    graph.add_edge("link_fix", "render")
    graph.add_edge("render", END)
    return graph.compile()


def report_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_report_graph()
    return _GRAPH
