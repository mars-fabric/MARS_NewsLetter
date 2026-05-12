"""Thin LLM client used by Stage 5 LangGraph nodes.

Stage 5 deliberately does NOT use ``cmbagent``'s agent/orchestration layer
(AutoGen, planning_and_control, etc.). It still piggybacks on ``cmbagent``'s
import-time monkeypatches that wire ``litellm`` to AWS Bedrock when AWS
credentials are present and ``OPENAI_API_KEY`` is not — that's how the rest of
the codebase already routes models, and re-implementing the alias map here
would just duplicate code that's been hardened.

The contract:
  * ``acomplete(messages, ...)`` → assistant string + usage dict
  * ``acomplete_json(schema_hint, messages, ...)`` → parsed dict, retrying on
    malformed JSON
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.logging import get_logger

logger = get_logger(__name__)


_CMBAGENT_IMPORTED = False


def _ensure_cmbagent_imported() -> None:
    """Trigger cmbagent's import-time monkeypatches without using its agents.

    cmbagent installs litellm.modify_params and the Bedrock alias map on
    import. We need those installed before calling litellm.acompletion, but we
    do NOT want to spin up any AutoGen/cmbagent agent.

    Also: copy AZURE_OPENAI_* → AZURE_* so litellm.acompletion(model='azure/…')
    picks up the credentials without each call having to pass api_base etc.
    """
    global _CMBAGENT_IMPORTED
    if _CMBAGENT_IMPORTED:
        return
    # Map AZURE_OPENAI_* to AZURE_* (what litellm reads natively).
    mapping = {
        "AZURE_API_KEY": "AZURE_OPENAI_API_KEY",
        "AZURE_API_BASE": "AZURE_OPENAI_ENDPOINT",
        "AZURE_API_VERSION": "AZURE_OPENAI_API_VERSION",
    }
    for litellm_key, our_key in mapping.items():
        if not os.environ.get(litellm_key) and os.environ.get(our_key):
            os.environ[litellm_key] = os.environ[our_key]

    try:
        import cmbagent  # noqa: F401 — side-effects only
        _CMBAGENT_IMPORTED = True
    except Exception as exc:  # pragma: no cover — CI without cmbagent
        logger.warning("stage5_cmbagent_import_failed", error=str(exc))
        _CMBAGENT_IMPORTED = True  # don't keep retrying


def default_model() -> str:
    """Pick a model name compatible with the active provider.

    Resolution order:
      1. ``STAGE5_MODEL`` env (verbatim — if you set it, you own routing).
      2. Azure: ``azure/<AZURE_OPENAI_DEPLOYMENT>`` when Azure is configured and
         OpenAI direct isn't (this is the litellm convention).
      3. AWS Bedrock: ``bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0``
         when AWS creds are present and Azure isn't.
      4. OpenAI direct: ``gpt-4o-mini``.
    """
    forced = os.environ.get("STAGE5_MODEL")
    if forced:
        return forced

    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_azure = bool(os.environ.get("AZURE_OPENAI_API_KEY")) and bool(
        os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    )
    has_aws = bool(os.environ.get("AWS_ACCESS_KEY_ID")) or bool(os.environ.get("AWS_PROFILE"))

    if not has_openai and has_azure:
        deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]
        return f"azure/{deployment}"
    if not has_openai and has_aws:
        return "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"
    return "gpt-4o-mini"


async def acomplete(
    *,
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    cost_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    extra_kwargs: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Single chat completion. Returns ``(content, usage)``."""
    _ensure_cmbagent_imported()
    import litellm

    model_name = model or default_model()
    kwargs: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
    }
    # Azure's newer gpt-4o/5.x deployments only accept ``max_completion_tokens``;
    # older OpenAI/Bedrock models still use ``max_tokens``. Pick the right key by
    # provider prefix to avoid a 400 from Azure.
    is_azure = isinstance(model_name, str) and model_name.startswith("azure/")
    if is_azure:
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
    if extra_kwargs:
        kwargs.update(extra_kwargs)

    # litellm.acompletion is a coroutine when available; fall back to
    # to_thread for older versions that only ship sync.
    acompletion = getattr(litellm, "acompletion", None)
    if acompletion is None:
        response = await asyncio.to_thread(litellm.completion, **kwargs)
    else:
        response = await acompletion(**kwargs)

    content = ""
    try:
        content = response.choices[0].message.content or ""
    except Exception:  # noqa: BLE001
        content = str(response)

    usage_obj = getattr(response, "usage", None)
    usage: Dict[str, Any] = {}
    if usage_obj is not None:
        usage = {
            "prompt_tokens": getattr(usage_obj, "prompt_tokens", None),
            "completion_tokens": getattr(usage_obj, "completion_tokens", None),
            "total_tokens": getattr(usage_obj, "total_tokens", None),
            "model": model_name,
        }
        if cost_callback:
            try:
                cost_callback(usage)
            except Exception:  # noqa: BLE001
                logger.exception("stage5_cost_callback_failed")

    return content, usage


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def _extract_json(text: str) -> Any:
    """Best-effort JSON extraction from a chat response."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response")

    m = _JSON_BLOCK.search(text)
    if m:
        return json.loads(m.group(1))

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        return json.loads(text[first : last + 1])

    first = text.find("[")
    last = text.rfind("]")
    if first != -1 and last != -1 and last > first:
        return json.loads(text[first : last + 1])

    return json.loads(text)


async def acomplete_json(
    *,
    messages: List[Dict[str, str]],
    schema_hint: str,
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    retries: int = 2,
    cost_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[Any, Dict[str, Any]]:
    """LLM call that must return JSON. Appends a schema hint and retries on parse error."""
    augmented = list(messages)
    augmented.append(
        {
            "role": "system",
            "content": (
                "Respond with ONLY a valid JSON value matching this schema. "
                "No prose, no markdown fences.\n\nSchema:\n" + schema_hint
            ),
        }
    )

    last_err: Optional[Exception] = None
    last_usage: Dict[str, Any] = {}
    for attempt in range(retries + 1):
        content, usage = await acomplete(
            messages=augmented,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            cost_callback=cost_callback,
        )
        last_usage = usage
        try:
            return _extract_json(content), usage
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            augmented.append(
                {
                    "role": "user",
                    "content": (
                        f"Your last response was not valid JSON ({exc}). "
                        "Re-emit ONLY the JSON value, nothing else."
                    ),
                }
            )
    raise ValueError(f"acomplete_json failed after {retries + 1} attempts: {last_err}")
