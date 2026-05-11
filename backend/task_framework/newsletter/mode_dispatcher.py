"""Dispatch an AI stage to the appropriate ``mars_cmbagent`` workflow.

Single entry-point that decides whether to run a stage as ``one_shot`` or
``planning_and_control_context_carryover`` (the variant PaperPulse / NewsPulse
use). Every other module talks to ``run_ai_stage`` instead of importing
``cmbagent`` directly so swapping providers / modes happens here.

Two passthrough surfaces are exposed to callers:

* ``model_overrides`` — every cmbagent role kwarg the UI exposes
  (``researcher_model``, ``engineer_model``, ``planner_model``, ...). Empty
  values are dropped so cmbagent's default model registry stays in effect.

* ``iteration_limits`` — every cmbagent iteration knob the UI exposes
  (``n_plan_reviews``, ``max_plan_steps``, ``max_n_attempts``,
  ``max_rounds_planning``, ``max_rounds_control``, ``max_rounds``). Only
  meaningful values are forwarded.

Optional ``cost_callback`` lets the caller inject a cost collector via
``WorkflowCallbacks(on_cost_update=...)`` so cmbagent emits per-token cost
rows back into the run header.

If ``mars_cmbagent`` is not importable (CI / unit tests) we fall back to a
deterministic stub so the rest of the pipeline can still be exercised.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from core.logging import get_logger
from models.newsletter_schemas import CmbAgentMode

logger = get_logger(__name__)

# Map our internal field name → cmbagent kwarg name. ``one_shot`` accepts a
# narrower set than ``planning_and_control``; planning-specific roles are
# silently dropped in one-shot mode.
_ONE_SHOT_MODEL_MAP = {
    "model": "researcher_model",          # default agent in one_shot
    "researcher_model": "researcher_model",
    "engineer_model": "engineer_model",
    "web_surfer_model": "web_surfer_model",
    "formatter_model": "default_formatter_model",
    "orchestration_model": "default_llm_model",
}
_PLANNING_MODEL_MAP = {
    "model": "engineer_model",            # primary executor in P&C
    "engineer_model": "engineer_model",
    "researcher_model": "researcher_model",
    "web_surfer_model": "web_surfer_model",
    "planner_model": "planner_model",
    "plan_reviewer_model": "plan_reviewer_model",
    "idea_maker_model": "idea_maker_model",
    "idea_hater_model": "idea_hater_model",
    "formatter_model": "default_formatter_model",
    "orchestration_model": "default_llm_model",
}

# Iteration knob name → cmbagent kwarg name, by mode.
_ONE_SHOT_LIMIT_MAP = {
    "max_rounds": "max_rounds",
    "max_n_attempts": "max_n_attempts",
}
_PLANNING_LIMIT_MAP = {
    "n_plan_reviews": "n_plan_reviews",
    "max_plan_steps": "max_plan_steps",
    "max_n_attempts": "max_n_attempts",
    "max_rounds_planning": "max_rounds_planning",
    "max_rounds_control": "max_rounds_control",
}


def _has_cmbagent() -> bool:
    try:
        import cmbagent  # noqa: F401
        return True
    except Exception:
        return False


def _map_kwargs(values: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    """Translate our internal field names to cmbagent's kwarg names.

    Empty / falsy values are dropped so cmbagent's defaults stay in effect.
    Integer 0 is preserved (max_n_attempts=0 etc. is theoretically possible)
    by checking ``is None`` rather than truthiness for numeric kwargs.
    """
    out: Dict[str, Any] = {}
    for our_key, cmbagent_key in mapping.items():
        value = values.get(our_key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        out[cmbagent_key] = value
    return out


def _split_overrides(config_overrides: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Pull any nested ``iteration_limits`` block out of the per-call overrides.

    Callers may pass either:
      ``{"researcher_model": "...", "n_plan_reviews": 1}``      (flat)
      ``{"researcher_model": "...", "iteration_limits": {...}}`` (nested)

    Both are accepted. Returns ``(model_overrides, iteration_limits)``.
    """
    nested = config_overrides.get("iteration_limits")
    if isinstance(nested, dict):
        models = {k: v for k, v in config_overrides.items() if k != "iteration_limits"}
        return models, dict(nested)
    # Flat: split by known iteration-knob names.
    iteration_keys = set(_PLANNING_LIMIT_MAP) | set(_ONE_SHOT_LIMIT_MAP)
    iters = {k: v for k, v in config_overrides.items() if k in iteration_keys}
    models = {k: v for k, v in config_overrides.items() if k not in iteration_keys}
    return models, iters


def _build_callbacks(cost_callback: Optional[Callable[[Dict[str, Any]], None]]):
    """Assemble cmbagent ``WorkflowCallbacks`` with our cost hook attached.

    Returns ``None`` when cmbagent isn't importable or when no cost callback
    was supplied — null callbacks are then chosen by cmbagent itself.
    """
    if cost_callback is None:
        return None
    try:
        from cmbagent.callbacks import WorkflowCallbacks  # type: ignore
    except Exception:
        return None
    return WorkflowCallbacks(on_cost_update=cost_callback)


async def run_ai_stage(
    *,
    prompt: str,
    mode: CmbAgentMode,
    work_dir: str,
    agent: str = "researcher",
    config_overrides: Optional[Dict[str, Any]] = None,
    max_rounds: int = 30,
    cost_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    plan_instructions: Optional[str] = None,
    researcher_instructions: Optional[str] = None,
    engineer_instructions: Optional[str] = None,
) -> str:
    """Run an LLM stage via mars_cmbagent in the requested mode and return the final text.

    Falls back to a stub when cmbagent is unavailable.
    """
    config_overrides = config_overrides or {}
    model_overrides, iteration_limits = _split_overrides(config_overrides)

    if not _has_cmbagent():
        logger.warning("cmbagent_unavailable_using_stub", mode=mode.value, agent=agent)
        return _stub_response(prompt, mode)

    callbacks = _build_callbacks(cost_callback)

    try:
        if mode == CmbAgentMode.ONE_SHOT:
            return await _run_one_shot(
                prompt=prompt, work_dir=work_dir, agent=agent,
                model_overrides=model_overrides, iteration_limits=iteration_limits,
                fallback_max_rounds=max_rounds, callbacks=callbacks,
            )
        if mode == CmbAgentMode.PLANNING_AND_CONTROL:
            try:
                return await _run_planning_control(
                    prompt=prompt, work_dir=work_dir, agent=agent,
                    model_overrides=model_overrides, iteration_limits=iteration_limits,
                    callbacks=callbacks,
                    plan_instructions=plan_instructions or "",
                    researcher_instructions=researcher_instructions or "",
                    engineer_instructions=engineer_instructions or "",
                )
            except Exception as pc_exc:
                # cmbagent's control phase raises "Step N failed after K
                # attempts" or "Phase control failed: ..." when the engineer
                # can't get a step's tool execution to succeed. Recover by
                # re-running the same task in one_shot mode — the researcher
                # alone is usually enough to produce a usable answer.
                err_str = str(pc_exc)
                pc_signature = (
                    "Phase control failed" in err_str
                    or "Step " in err_str and "failed after" in err_str
                    or "Max attempts" in err_str
                )
                if not pc_signature:
                    raise
                logger.warning(
                    "planning_and_control_failed_falling_back_to_one_shot",
                    mode=mode.value, agent=agent, error=err_str[:200],
                )
                # Fold the planner / researcher / engineer instructions into
                # the one_shot prompt so the executor still has the guidance
                # the planner phase would have provided.
                fallback_prompt = _merge_instructions_for_one_shot(
                    prompt=prompt,
                    plan_instructions=plan_instructions,
                    researcher_instructions=researcher_instructions,
                    engineer_instructions=engineer_instructions,
                )
                return await _run_one_shot(
                    prompt=fallback_prompt, work_dir=work_dir, agent=agent,
                    model_overrides=model_overrides, iteration_limits=iteration_limits,
                    fallback_max_rounds=max_rounds, callbacks=callbacks,
                )
    except Exception as exc:
        logger.error("ai_stage_failed", mode=mode.value, error=str(exc))
        raise

    raise ValueError(f"Unknown mode: {mode}")


def _merge_instructions_for_one_shot(
    *,
    prompt: str,
    plan_instructions: Optional[str],
    researcher_instructions: Optional[str],
    engineer_instructions: Optional[str],
) -> str:
    """Compose a single one_shot prompt that carries researcher/engineer
    guidance from a failed planning_and_control attempt.

    ``plan_instructions`` is intentionally **dropped** — planner prompts
    typically describe the *output of the planning phase* (e.g. "emit a
    numbered list of search queries"), which collides with the researcher's
    final-output format and makes the LLM emit a query plan instead of real
    results. Researcher / engineer guidance describes the final deliverable
    and is kept.
    """
    extras: list[str] = []
    if researcher_instructions:
        extras.append("## Researcher guidance\n" + researcher_instructions.strip())
    if engineer_instructions:
        extras.append("## Engineer guidance\n" + engineer_instructions.strip())
    if not extras:
        return prompt
    note = (
        "## Mode note\n"
        "Planning-and-control failed for this step; this is the recovery one_shot pass. "
        "Plan internally, then **execute** the work and emit the final deliverable in the "
        "exact format the researcher guidance describes. Do not output a planning artefact."
    )
    return prompt + "\n\n" + note + "\n\n" + "\n\n".join(extras)


async def _run_one_shot(*, prompt: str, work_dir: str, agent: str,
                        model_overrides: Dict[str, Any],
                        iteration_limits: Dict[str, Any],
                        fallback_max_rounds: int,
                        callbacks: Any = None) -> str:
    """Invoke ``cmbagent.one_shot`` via to_thread (cmbagent is sync)."""
    import asyncio
    import cmbagent

    def _call():
        kwargs: Dict[str, Any] = {
            "task": prompt,
            "agent": agent,
            "work_dir": work_dir,
            "max_rounds": fallback_max_rounds,
            **_map_kwargs(model_overrides, _ONE_SHOT_MODEL_MAP),
            **_map_kwargs(iteration_limits, _ONE_SHOT_LIMIT_MAP),
        }
        if callbacks is not None:
            kwargs["callbacks"] = callbacks
        return cmbagent.one_shot(**kwargs)

    result = await asyncio.to_thread(_call)
    return _extract_text(result, agent=agent)


async def _run_planning_control(*, prompt: str, work_dir: str, agent: str,
                                model_overrides: Dict[str, Any],
                                iteration_limits: Dict[str, Any],
                                callbacks: Any = None,
                                plan_instructions: str = "",
                                researcher_instructions: str = "",
                                engineer_instructions: str = "") -> str:
    """Always uses ``planning_and_control_context_carryover`` (same as PaperPulse).

    Per-stage instructions (``plan_instructions``, ``researcher_instructions``,
    ``engineer_instructions``) are forwarded so each stage can shape what the
    planner / researcher / executor focuses on without inflating the main task
    prompt.
    """
    import asyncio
    from cmbagent.workflows.planning_control import planning_and_control_context_carryover

    def _call():
        kwargs: Dict[str, Any] = {
            "task": prompt,
            "work_dir": work_dir,
            **_map_kwargs(model_overrides, _PLANNING_MODEL_MAP),
            **_map_kwargs(iteration_limits, _PLANNING_LIMIT_MAP),
        }
        if plan_instructions:
            kwargs["plan_instructions"] = plan_instructions
        if researcher_instructions:
            kwargs["researcher_instructions"] = researcher_instructions
        if engineer_instructions:
            kwargs["engineer_instructions"] = engineer_instructions
        if callbacks is not None:
            kwargs["callbacks"] = callbacks
        return planning_and_control_context_carryover(**kwargs)

    result = await asyncio.to_thread(_call)
    return _extract_text(result, agent=agent)


_MD_CODE_BLOCK_RE = r"```(?:markdown)?\s*\n([\s\S]*?)```"
# The researcher_response_formatter wraps the answer in a python "save to
# file" script: ``content = '<repr-escaped markdown>'``. Recovering the
# original markdown means matching ``content = ...`` and ast.literal_eval-ing
# the string literal that follows.
_FORMATTER_CONTENT_RE = r"content\s*=\s*((?:[rRbBuU]?['\"]).*?(?<!\\)['\"](?:\s*\\?\n\s*['\"][^'\"]*['\"])*)"


def _strip_code_fence(text: str) -> str:
    import re
    if not text:
        return text
    m = re.search(_MD_CODE_BLOCK_RE, text)
    return m.group(1).strip() if m else text


def _unwrap_formatter_payload(content: str) -> Optional[str]:
    """Recover the markdown the researcher_response_formatter packed into a
    ``content = repr(...)`` line inside its python save-script.

    Returns ``None`` if the message is not a save-script wrapper.
    """
    import ast
    import re
    if not content or "content =" not in content:
        return None
    block_match = re.search(r"```python\s*\n([\s\S]*?)```", content)
    body = block_match.group(1) if block_match else content
    m = re.search(r"^\s*content\s*=\s*(.+?)\s*$", body, flags=re.MULTILINE)
    if not m:
        return None
    literal = m.group(1)
    try:
        return ast.literal_eval(literal)
    except (SyntaxError, ValueError):
        pass
    lines = body.splitlines()
    start_idx = next((i for i, line in enumerate(lines)
                      if line.strip().startswith("content")), None)
    if start_idx is None:
        return None
    accum = lines[start_idx].split("=", 1)[1].strip()
    for nxt in lines[start_idx + 1:]:
        if re.match(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=", nxt):
            break
        accum += "\n" + nxt
        try:
            return ast.literal_eval(accum)
        except (SyntaxError, ValueError):
            continue
    return None


def _from_chat_history(chat_history: Any, agent: str) -> Optional[str]:
    """Walk chat_history backwards and pick the last useful message."""
    if not isinstance(chat_history, list) or not chat_history:
        return None
    preferred = [f"{agent}_response_formatter", f"{agent}_nest", agent,
                 "researcher_response_formatter", "engineer_response_formatter",
                 "researcher", "engineer"]
    for name in preferred:
        for msg in reversed(chat_history):
            if isinstance(msg, dict) and msg.get("name") == name:
                content = msg.get("content")
                if not (isinstance(content, str) and content.strip()):
                    continue
                unwrapped = _unwrap_formatter_payload(content)
                if unwrapped:
                    import re
                    return re.sub(r"^\s*<!--\s*filename:[^>]*-->\s*\n?", "",
                                  unwrapped, count=1)
                stripped = _strip_code_fence(content)
                if stripped:
                    return stripped
    # Final fallback: longest non-empty assistant message.
    best: Optional[str] = None
    for msg in reversed(chat_history):
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                unwrapped = _unwrap_formatter_payload(content)
                candidate = unwrapped or _strip_code_fence(content)
                if candidate and (best is None or len(candidate) > len(best)):
                    best = candidate
    if best:
        import re
        return re.sub(r"^\s*<!--\s*filename:[^>]*-->\s*\n?", "", best, count=1)
    return None


def _extract_text(result: Any, agent: str = "researcher") -> str:
    """Flatten cmbagent's workflow result to plain text."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        text = _from_chat_history(result.get("chat_history"), agent)
        if text:
            return text
        final_ctx = result.get("final_context")
        if isinstance(final_ctx, dict):
            for key in ("final_response", "response", "text", "content", "output", "summary"):
                if isinstance(final_ctx.get(key), str) and final_ctx[key].strip():
                    return final_ctx[key]
        for key in ("final_response", "response", "text", "content", "output", "summary"):
            if isinstance(result.get(key), str) and result[key].strip():
                return result[key]
        noisy = {"chat_history", "final_context", "run_id", "workflow_id",
                 "phase_timings", "total_time", "initialization_time", "execution_time"}
        return "\n".join(f"**{k}**: {v}" for k, v in result.items()
                         if not k.startswith("_") and k not in noisy)
    return str(result)


def _stub_response(prompt: str, mode: CmbAgentMode) -> str:
    return (
        f"# [stub] {mode.value}\n\n"
        f"_(mars_cmbagent is not installed in this environment — returning the prompt verbatim "
        f"so the pipeline can be smoke-tested.)_\n\n"
        f"```\n{prompt[:2000]}\n```\n"
    )
