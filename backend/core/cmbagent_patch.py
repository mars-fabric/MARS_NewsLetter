"""Patch cmbagent's executor-output truncation threshold.

mars_cmbagent 1.x shipped ``MessageContentTruncator`` in
``cmbagent.handoffs.message_limiting`` — a per-message char cap (default
25 000 chars) that caused the ``[content truncated: N → M chars]`` banner
to appear inside long newsletter drafts.

mars_cmbagent 2.0 removed that subsystem entirely. Truncation is now
token-based and scoped to executor outputs only, implemented via
``HeadTailTokenTruncate`` in ``cmbagent.utils.message_transforms``.
The Stage 4 section-by-section writer means no newsletter content passes
through cmbagent's message history at all, so per-message char caps are
no longer relevant.

This module tries the v1.x patch path first, then the v2.0 path. Both
are optional — if neither applies the function is a safe no-op.

Environment knobs
-----------------
CMBAGENT_MAX_MSG_CONTENT_CHARS   v1.x char cap (default 200 000)
CMBAGENT_EXECUTOR_TOKEN_THRESHOLD v2.0 executor-output token threshold
                                  (default: keep cmbagent's own default)
"""

from __future__ import annotations

import os

from core.logging import get_logger

logger = get_logger(__name__)


_APPLIED = False


def apply_cmbagent_message_limit_patch() -> int:
    """Patch cmbagent's message truncation at import time. Idempotent.

    Returns the active limit (chars for v1.x, tokens for v2.0) so callers
    can log it, or 0 when no patch was applied.
    """
    global _APPLIED
    if _APPLIED:
        return 0

    _APPLIED = True

    # ── v1.x path ────────────────────────────────────────────────────────────
    try:
        import cmbagent.handoffs.message_limiting as _cm_ml  # type: ignore
    except Exception:
        pass  # v2.0 — module removed, fall through to v2 path
    else:
        try:
            new_limit = int(os.getenv("CMBAGENT_MAX_MSG_CONTENT_CHARS", "200000"))
        except ValueError:
            new_limit = 200_000

        old_limit = int(getattr(_cm_ml, "_MAX_MSG_CONTENT_CHARS", 25_000))
        _cm_ml._MAX_MSG_CONTENT_CHARS = new_limit

        truncator_cls = getattr(_cm_ml, "MessageContentTruncator", None)
        if truncator_cls is not None:
            original_init = truncator_cls.__init__

            def _patched_init(self, max_chars: int = new_limit):  # noqa: D401
                original_init(self, max_chars=max_chars)

            truncator_cls.__init__ = _patched_init

        logger.info(
            "cmbagent_message_limit_patched_v1",
            old_limit=old_limit,
            new_limit=new_limit,
        )
        return new_limit

    # ── v2.0 path ────────────────────────────────────────────────────────────
    # HeadTailTokenTruncate is instantiated inside register_all_hand_offs with
    # a hardcoded threshold_tokens=2000. Override the class default so future
    # instances (and the one created at CMBAgent init) pick up the env value.
    threshold_env = os.getenv("CMBAGENT_EXECUTOR_TOKEN_THRESHOLD")
    if threshold_env:
        try:
            new_threshold = int(threshold_env)
        except ValueError:
            logger.warning("cmbagent_patch_invalid_threshold", value=threshold_env)
            return 0

        try:
            from cmbagent.utils.message_transforms import HeadTailTokenTruncate  # type: ignore
        except Exception as exc:
            logger.warning("cmbagent_patch_v2_import_failed", error=str(exc))
            return 0

        original_init = HeadTailTokenTruncate.__init__

        def _patched_v2_init(
            self,
            threshold_tokens: int = new_threshold,
            **kwargs,
        ):
            original_init(self, threshold_tokens=threshold_tokens, **kwargs)

        HeadTailTokenTruncate.__init__ = _patched_v2_init  # type: ignore[method-assign]
        logger.info(
            "cmbagent_executor_threshold_patched_v2",
            new_threshold_tokens=new_threshold,
        )
        return new_threshold

    # v2.0 and no override requested — no patch needed (section-by-section
    # Stage 4 means newsletter content never enters cmbagent message history).
    logger.debug("cmbagent_patch_v2_no_op")
    return 0
