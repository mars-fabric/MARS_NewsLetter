"""Stage 5 — LangGraph-based Report Builder, Evaluator, and Dashboard.

This package replaces the legacy ``cmbagent``-driven critic/editor/score-card
flow in ``helpers.run_stage_5`` with a 22-node LangGraph DAG. The runner is
signature-compatible so the orchestrator can switch implementations behind a
flag.

Public surface:
    run_stage_5_langgraph  — async entry point matching helpers.run_stage_5
    build_stage5_graph     — compile a fresh graph (e.g. for visualization)
"""

from .graph import build_stage5_graph
from .runner import run_stage_5_langgraph

__all__ = ["run_stage_5_langgraph", "build_stage5_graph"]
