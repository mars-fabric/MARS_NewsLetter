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

import os
from typing import Any, Callable, Dict, Optional

from core.logging import get_logger
from models.newsletter_schemas import CmbAgentMode

logger = get_logger(__name__)


def _stage_timeout_seconds() -> int:
    """Hard cap for any single AI stage call (default 240s).

    Prevents stage rows from sitting in `running` forever when an upstream
    provider/tool call stalls.
    """
    raw = os.getenv("NEWSLETTER_AI_STAGE_TIMEOUT_S", "240").strip()
    try:
        val = int(raw)
    except ValueError:
        return 240
    return max(60, val)


# ──────────────────────────────────────────────────────────────────────────────
# cmbagent hardening: the upstream `plan_setter` tool signature declares
# `needed_agents: List[Literal["engineer","researcher","idea_maker",
# "idea_hater","camb_context","aas_keyword_finder"]]`, so the LLM planner
# frequently requests `camb_context` / `aas_keyword_finder` even on a general
# newsletter task where those agents don't exist. Upstream then calls
# `cmbagent_instance.get_agent_object_from_name(agent)` inside
# `build_agent_instructions`, which prints an error and does `sys.exit()` on
# an unknown agent. `SystemExit` is a `BaseException` and escapes past
# `asyncio.to_thread`, killing the uvicorn worker and every in-flight task.
#
# We fix this once, at import time, by monkey-patching
# `cmbagent.functions.planning.build_agent_instructions` to silently drop
# unknown agents instead of exiting. Idempotent: only patches on first import.
# ──────────────────────────────────────────────────────────────────────────────
_CMBAGENT_HARDENING_APPLIED = False


def _apply_cmbagent_hardening() -> None:
    global _CMBAGENT_HARDENING_APPLIED
    if _CMBAGENT_HARDENING_APPLIED:
        return
    try:
        from cmbagent.functions import planning as _planning  # type: ignore
    except Exception as exc:  # pragma: no cover — best-effort
        logger.debug("cmbagent_hardening_skipped_import_failed", error=str(exc))
        _CMBAGENT_HARDENING_APPLIED = True
        return

    def _hardened_build_agent_instructions(cmbagent_instance, needed_agents):
        # Filter out agents that don't exist on this instance, silently — the
        # planner LLM occasionally hallucinates `camb_context` /
        # `aas_keyword_finder` on non-cosmology tasks and the upstream call
        # `sys.exit()`s if we hand them through.
        known: list = []
        for name in needed_agents or []:
            try:
                obj = cmbagent_instance.get_agent_object_from_name(name)
            except SystemExit:
                logger.warning("cmbagent_dropped_unknown_agent_from_plan", agent=name)
                continue
            if obj is None:
                logger.warning("cmbagent_dropped_unknown_agent_from_plan", agent=name)
                continue
            known.append(name)

        if not known:
            # Never leave the planner with zero agents — fall back to the
            # workhorse pair that every workflow supports.
            known = ["engineer", "researcher"]
            logger.warning("cmbagent_planner_agent_list_empty_defaulted_to_engineer_researcher")

        header = f"The plan must strictly involve only the following agents: {', '.join(known)}\n"
        body = r"""
**AGENT ROLES AND INSTRUCTIONS**
Here are the agents that are needed to carry out the plan, along with their full instructions.
When creating sub-task instructions, you MUST respect each agent's constraints and conventions described below.
Do NOT specify implementation details that conflict with the agent's instructions (e.g., don't specify absolute paths if the agent uses relative paths, don't specify variable names, etc.).
Focus on WHAT should be accomplished, not HOW the agent should implement it.

You must carefully check that the sub-taskinstructions proposed for each agent are consistent with the agent's instructions and rules.

"""
        for agent in set(known):
            try:
                agent_object = cmbagent_instance.get_agent_object_from_name(agent)
            except SystemExit:
                continue
            if agent_object is None:
                continue
            info = getattr(agent_object, "info", {}) or {}
            body += (
                f"\n---\n**Agent: {agent}**\n"
                f"**Description:** {info.get('description', 'No description available.')}\n"
                f"**Full Agent Instructions:**\n"
                f"{info.get('instructions', 'No instructions available.')}\n---\n"
            )
        body += r"""
You must not invoke any other agent than the ones listed above.

**IMPORTANT PLANNING GUIDELINES:**
- Keep sub-task instructions high-level (WHAT to do, not HOW)
- Do NOT specify exact variable names, function names, or code snippets
- Do NOT specify exact file paths - let the agent decide based on its conventions
- Do NOT specify exact library calls or API usage
- Focus on the goal and expected outputs, not implementation details
"""
        return header + body

    _planning.build_agent_instructions = _hardened_build_agent_instructions
    _CMBAGENT_HARDENING_APPLIED = True
    logger.info("cmbagent_hardening_applied", patched="build_agent_instructions")


_apply_cmbagent_hardening()

# Map our internal field name → cmbagent kwarg name. ``one_shot`` accepts a
# narrower set than ``planning_and_control``; planning-specific roles are
# silently dropped in one-shot mode.
_ONE_SHOT_MODEL_MAP = {
    "model": "researcher_model",          # default agent in one_shot
    "researcher_model": "researcher_model",
    "engineer_model": "engineer_model",
    "orchestration_model": "default_llm_model",
    "evaluator_model": "default_evaluator_model",
}
_PLANNING_MODEL_MAP = {
    "model": "engineer_model",            # primary executor in P&C
    "engineer_model": "engineer_model",
    "researcher_model": "researcher_model",
    "planner_model": "planner_model",
    "plan_reviewer_model": "plan_reviewer_model",
    "idea_maker_model": "idea_maker_model",
    "idea_hater_model": "idea_hater_model",
    "orchestration_model": "default_llm_model",
    "evaluator_model": "default_evaluator_model",
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


def _detect_default_model() -> Optional[str]:
    """Return the best available model string from environment, so cmbagent
    never falls back to its hardcoded Gemini defaults when Gemini is not configured.

    Priority: Azure OpenAI → OpenAI → Anthropic → None (use cmbagent default).
    """
    import os
    azure_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
    if azure_key and azure_endpoint and azure_deployment:
        # Ensure LiteLLM Azure env aliases are set (litellm reads AZURE_API_KEY /
        # AZURE_API_BASE in addition to the OpenAI-SDK convention).
        os.environ.setdefault("AZURE_API_KEY", azure_key)
        os.environ.setdefault("AZURE_API_BASE", azure_endpoint)
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
        os.environ.setdefault("AZURE_API_VERSION", api_version)
        return f"azure/{azure_deployment}"
    if os.getenv("OPENAI_API_KEY", "").strip():
        return "gpt-4o"
    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        return "claude-3-5-sonnet-20241022"
    return None


def _inject_default_model(model_overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Inject the auto-detected model for every role that isn't already overridden.

    cmbagent has a hardcoded default config_list that uses Gemini models. When the
    newsletter is configured for Azure OpenAI (and Gemini API key is absent), every
    un-overridden role silently falls back to Gemini and then hangs on auth failures.
    We prevent this by filling all role slots with the detected provider model.
    """
    default = _detect_default_model()
    if not default:
        return model_overrides
    out = dict(model_overrides)
    # All role keys that either _ONE_SHOT_MODEL_MAP or _PLANNING_MODEL_MAP can receive.
    all_role_keys = (
        "model", "researcher_model", "engineer_model", "planner_model",
        "plan_reviewer_model", "idea_maker_model", "idea_hater_model",
        "web_surfer_model", "formatter_model", "orchestration_model",
    )
    injected: list[str] = []
    for key in all_role_keys:
        if not out.get(key):
            out[key] = default
            injected.append(key)
    if injected:
        logger.info("auto_injected_default_model", model=default, roles=injected)
    return out


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
    max_rounds: int = 20,
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
                    or "timed out" in err_str.lower()
                    or "timeout" in err_str.lower()
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
                # Cap fallback rounds lower than the primary budget — the
                # researcher has already seen P&C try to solve this; it
                # should converge faster in one_shot.
                fallback_rounds = min(max_rounds, 15)
                return await _run_one_shot(
                    prompt=fallback_prompt, work_dir=work_dir, agent=agent,
                    model_overrides=model_overrides, iteration_limits=iteration_limits,
                    fallback_max_rounds=fallback_rounds, callbacks=callbacks,
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
    """Invoke ``cmbagent.one_shot`` via to_thread (cmbagent is sync).

    ``enable_ag2_free_tools=True`` is set unconditionally so DDGS, Wikipedia,
    ArXiv and the other free LangChain/CrewAI web-search tools are wired
    into the researcher agent. Without it, the researcher cannot actually
    reach the web and Stage 2/3/4 collapse into hallucinated content.
    """
    import asyncio
    import cmbagent

    model_overrides = _inject_default_model(model_overrides)

    def _call():
        kwargs: Dict[str, Any] = {
            "task": prompt,
            "agent": agent,
            "work_dir": work_dir,
            "max_rounds": fallback_max_rounds,
            "enable_ag2_free_tools": True,
            **_map_kwargs(model_overrides, _ONE_SHOT_MODEL_MAP),
            **_map_kwargs(iteration_limits, _ONE_SHOT_LIMIT_MAP),
        }
        if callbacks is not None:
            kwargs["callbacks"] = callbacks
        return cmbagent.one_shot(**kwargs)

    timeout_s = _stage_timeout_seconds()
    try:
        result = await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise RuntimeError(
            f"one_shot stage timed out after {timeout_s}s (agent={agent}). "
            "Check provider credentials/model routing and reduce stage complexity."
        ) from exc
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

    model_overrides = _inject_default_model(model_overrides)

    def _call():
        kwargs: Dict[str, Any] = {
            "task": prompt,
            "work_dir": work_dir,
            # DDGS + LangChain + CrewAI free tools — same rationale as the
            # one_shot path. In planning_and_control the researcher agent is
            # the primary consumer of web search.
            "enable_ag2_free_tools": True,
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
        # cmbagent's `get_agent_object_from_name` calls `sys.exit()` when the
        # planner hallucinates a non-existent agent (e.g. `camb_context`,
        # `aas_keyword_finder` in a general-purpose newsletter task).
        # `SystemExit` is a `BaseException`, so if we don't catch it here it
        # propagates past `asyncio.to_thread`, escapes the FastAPI request
        # handler, and kills the uvicorn worker — taking every in-flight
        # task down with it. Trap it and re-raise as a normal RuntimeError so
        # the stage fails cleanly and the server keeps serving.
        try:
            return planning_and_control_context_carryover(**kwargs)
        except SystemExit as exc:
            raise RuntimeError(
                f"cmbagent planning_and_control aborted via sys.exit(): {exc!r}. "
                "This usually means the plan_setter agent requested an "
                "unknown agent name via set_plan_constraints \u2014 check the "
                "stage console log for the offending needed_agents list."
            ) from exc

    timeout_s = _stage_timeout_seconds()
    try:
        result = await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise RuntimeError(
            f"planning_and_control stage timed out after {timeout_s}s (agent={agent})."
        ) from exc
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
