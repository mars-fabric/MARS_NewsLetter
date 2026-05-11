"""Bridge the ``CredentialVault`` (backend persistence) with cmbagent's
``ProviderRegistry`` (runtime provider resolution).

Called:
  1. On server startup (lifespan)
  2. After any credential store/update/delete via the API
  3. Explicitly via ``POST /api/providers/sync``

Ported from ``MARS-PaperPulse/backend/services/config_bridge.py``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from services.credential_vault import CredentialVault

logger = logging.getLogger(__name__)


class ConfigBridge:
    """Sync credentials from multiple sources into cmbagent's ``ProviderRegistry``."""

    @staticmethod
    def sync_all() -> Dict[str, str]:
        """Full sync: ``.env`` → vault → registry → ``os.environ``.

        Priority (highest wins):
          1. ``CredentialVault`` (UI-set)
          2. ``os.environ`` / ``.env`` (admin-set)
        """
        try:
            from cmbagent.providers.registry import ProviderRegistry  # type: ignore
        except ImportError:
            logger.warning("cmbagent.providers not available — skipping credential sync")
            return {"error": "cmbagent.providers not importable"}

        registry = ProviderRegistry.instance()
        vault = CredentialVault()
        results: Dict[str, str] = {}

        registry.refresh_from_env()

        for provider_id, creds in vault.get_all().items():
            if creds:
                try:
                    registry.set_credentials(provider_id, creds)
                    results[provider_id] = "synced_from_vault"
                except ValueError:
                    logger.warning("Provider '%s' in vault but not in registry, skipping", provider_id)
                    results[provider_id] = "provider_not_in_registry"
            else:
                results[provider_id] = "empty_in_vault"

        try:
            from cmbagent.llm_provider import get_provider_config  # type: ignore
            get_provider_config().refresh()
        except Exception as exc:
            logger.warning("Failed to refresh legacy LLMProviderConfig: %s", exc)

        logger.info("Config sync complete: %s", results)
        return results

    @staticmethod
    async def sync_and_validate(provider_id: str) -> Dict[str, Any]:
        """Sync a single provider and validate its credentials."""
        try:
            from cmbagent.providers.registry import ProviderRegistry  # type: ignore
        except ImportError:
            return {"status": "error", "message": "cmbagent.providers not importable"}

        registry = ProviderRegistry.instance()
        vault = CredentialVault()

        creds = vault.get(provider_id)
        if not creds:
            return {"status": "not_configured", "message": "No credentials stored"}

        registry.set_credentials(provider_id, creds)
        result = await registry.validate_provider(provider_id)

        try:
            from cmbagent.llm_provider import get_provider_config  # type: ignore
            get_provider_config().refresh()
        except Exception:
            pass

        return {
            "status": "validated" if result.success else "invalid",
            "message": result.message,
            "latency_ms": result.latency_ms,
            "error_details": result.error_details,
        }
