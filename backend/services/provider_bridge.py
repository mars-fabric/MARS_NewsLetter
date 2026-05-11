"""Push provider credentials from .env into cmbagent's ProviderRegistry.

Without this bridge, cmbagent only sees creds that were exported in the same
shell that started the server — Python's ``os.environ`` is enough for litellm
in most cases, but cmbagent's ProviderRegistry caches its own copy at import
time. This function nudges it to refresh so credentials picked up via
``python-dotenv`` (or env_file in compose) actually take effect.
"""

from __future__ import annotations

from core.logging import get_logger

logger = get_logger(__name__)


def sync_providers_from_env() -> None:
    try:
        from cmbagent.providers import ProviderRegistry  # type: ignore
    except Exception:
        logger.info("provider_registry_unavailable")
        return

    try:
        registry = ProviderRegistry()
        # Most builds expose either ``refresh`` or ``reload_from_env`` — try both.
        for method_name in ("reload_from_env", "refresh", "sync_from_env"):
            method = getattr(registry, method_name, None)
            if callable(method):
                method()
                logger.info("provider_registry_synced", method=method_name)
                return
        logger.info("provider_registry_no_refresh_method_found")
    except Exception as exc:
        logger.warning("provider_registry_sync_failed", error=str(exc))
