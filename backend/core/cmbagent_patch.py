"""Raise cmbagent's per-message content cap.

cmbagent ships ``MessageContentTruncator`` with a hardcoded
``_MAX_MSG_CONTENT_CHARS = 25_000``. Any LLM message longer than that gets
spliced into ``head[:0.7*max] + banner + tail[:0.3*max]`` with a
``... [content truncated: N → M chars] ...`` marker — and that marker has
been showing up *inside* the final newsletter when the Stage 4 writer
produces a 60–80 KB draft.

cmbagent does not expose an environment knob for the per-message cap, so we
patch the constant at import time. The constructor is also rebound so any
``MessageContentTruncator(...)`` constructed later picks up the new default
when no explicit ``max_chars`` is passed.

Set ``CMBAGENT_MAX_MSG_CONTENT_CHARS`` to override the limit; default 200 000
chars (~50 k tokens) is safe for Claude Sonnet / GPT-4o class models.
"""

from __future__ import annotations

import os

from core.logging import get_logger

logger = get_logger(__name__)


_APPLIED = False


def apply_cmbagent_message_limit_patch() -> int:
    """Raise the per-message char cap inside ``cmbagent.handoffs.message_limiting``.

    Idempotent — safe to call from multiple entry points (run.py and main.py).
    Returns the active limit so callers can log it.
    """
    global _APPLIED
    if _APPLIED:
        try:
            import cmbagent.handoffs.message_limiting as _cm_ml
            return int(getattr(_cm_ml, "_MAX_MSG_CONTENT_CHARS", 0))
        except Exception:
            return 0

    try:
        new_limit = int(os.getenv("CMBAGENT_MAX_MSG_CONTENT_CHARS", "200000"))
    except ValueError:
        new_limit = 200_000

    try:
        import cmbagent.handoffs.message_limiting as _cm_ml
    except Exception as exc:
        logger.warning("cmbagent_patch_skipped_import_failed", error=str(exc))
        _APPLIED = True
        return 0

    old_limit = int(getattr(_cm_ml, "_MAX_MSG_CONTENT_CHARS", 25_000))
    _cm_ml._MAX_MSG_CONTENT_CHARS = new_limit

    truncator_cls = getattr(_cm_ml, "MessageContentTruncator", None)
    if truncator_cls is not None:
        original_init = truncator_cls.__init__

        def _patched_init(self, max_chars: int = new_limit):  # noqa: D401
            original_init(self, max_chars=max_chars)

        truncator_cls.__init__ = _patched_init

    _APPLIED = True
    logger.info(
        "cmbagent_message_limit_patched",
        old_limit=old_limit,
        new_limit=new_limit,
    )
    return new_limit
