"""Provider Management API — multi-provider LLM credential management.

Mirrors ``MARS-PaperPulse/backend/routers/providers.py`` so the same UI can talk
to either backend. NewsLetter retains a couple of slim helper endpoints
(``/status``, ``/configured``) that the previous lightweight dialog used.

Endpoints:

* ``GET    /api/providers``                    — full provider list (registry + creds + models)
* ``GET    /api/providers/status``             — slim summary (back-compat)
* ``GET    /api/providers/configured``         — list of configured provider ids (back-compat)
* ``GET    /api/providers/{id}``               — single provider detail
* ``POST   /api/providers/{id}/credentials``   — store creds in vault, sync to registry
* ``POST   /api/providers/{id}/test``          — test creds without storing
* ``DELETE /api/providers/{id}/credentials``   — remove stored creds
* ``GET    /api/providers/models/available``   — flat models list across all configured providers
* ``POST   /api/providers/sync``               — force re-sync of .env + vault → registry
* ``POST   /api/providers/refresh``            — re-read env (legacy alias for /sync)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from models.provider_schemas import ProviderCredentialInput

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["Providers"])


def _get_registry():
    try:
        from cmbagent.providers.registry import ProviderRegistry  # type: ignore
        return ProviderRegistry.instance()
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"Provider system not available: {exc}")


def _get_vault():
    from services.credential_vault import CredentialVault
    return CredentialVault()


def _get_bridge():
    from services.config_bridge import ConfigBridge
    return ConfigBridge


def _slim_provider(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "provider_id": p.get("provider_id"),
        "display_name": p.get("display_name"),
        "status": p.get("status"),
        "model_count": len(p.get("models") or []),
        "credentials_present": [
            f.get("name") for f in (p.get("credential_fields") or []) if f.get("has_value")
        ],
        "has_credentials": any(
            f.get("has_value") for f in (p.get("credential_fields") or [])
        ),
    }


# ─── List / Detail ─────────────────────────────────────────────────────────

@router.get("")
async def list_providers() -> Dict[str, Any]:
    """Full provider list — credential schema, masked values, model catalog, status."""
    registry = _get_registry()
    providers = registry.list_providers()
    try:
        active_obj = registry.get_active_provider()
        active = getattr(active_obj, "provider_id", None) if active_obj else None
    except Exception:
        active = None
    total_models = sum(len(p.get("models", [])) for p in providers)
    return {
        "providers": providers,
        "active_provider": active,
        "total_models": total_models,
        "timestamp": time.time(),
    }


@router.get("/status")
async def get_provider_status() -> Dict[str, Any]:
    """Slim summary — kept for backward compat with the older settings dialog."""
    registry = _get_registry()
    raw = registry.list_providers()
    slim = [_slim_provider(p) for p in raw]
    configured = [p for p in slim if p["status"] == "configured"]
    try:
        active_obj = registry.get_active_provider()
        active = getattr(active_obj, "provider_id", None) if active_obj else None
    except Exception:
        active = None
    try:
        all_models = registry.get_available_models_for_configured_providers() or []
    except Exception:
        all_models = []
    return {
        "providers": slim,
        "active_provider": active,
        "configured_count": len(configured),
        "total_models": len(all_models),
    }


@router.get("/configured")
async def get_configured_providers() -> List[str]:
    registry = _get_registry()
    return [p["provider_id"] for p in registry.list_providers() if p.get("status") == "configured"]


@router.get("/models/available")
async def get_available_models() -> Dict[str, Any]:
    """Flat ``[{value,label}]`` model list across every configured provider."""
    registry = _get_registry()
    models = registry.get_available_models_for_configured_providers() or []
    providers_seen = {m.get("provider", "") for m in models}
    return {
        "models": models,
        "provider_count": len(providers_seen),
        "timestamp": time.time(),
    }


@router.get("/{provider_id}")
async def get_provider_detail(provider_id: str) -> Dict[str, Any]:
    registry = _get_registry()
    for p in registry.list_providers():
        if p["provider_id"] == provider_id:
            return p
    raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")


# ─── Credential Operations ─────────────────────────────────────────────────

@router.post("/{provider_id}/credentials")
async def store_provider_credentials(provider_id: str, body: ProviderCredentialInput) -> Dict[str, Any]:
    """Persist credentials to the encrypted vault and sync them into the registry.

    Rolls back the vault write if the registry sync raises an unexpected error,
    so we never end up with orphaned creds that fail every restart.
    """
    vault = _get_vault()
    bridge = _get_bridge()
    registry = _get_registry()

    known_providers = {p["provider_id"] for p in registry.list_providers()}
    if provider_id not in known_providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    had_prior = bool(vault.get(provider_id))
    prior_creds = vault.get(provider_id) if had_prior else None

    vault.set(provider_id, body.credentials)

    try:
        result = await bridge.sync_and_validate(provider_id)
    except Exception as exc:
        logger.exception("sync_and_validate failed for %s; rolling back vault write", provider_id)
        if had_prior and prior_creds is not None:
            vault.set(provider_id, prior_creds)
        else:
            vault.remove(provider_id)
        raise HTTPException(status_code=500, detail=f"Failed to sync credentials: {exc}")

    models_added = 0
    for p in registry.list_providers():
        if p["provider_id"] == provider_id:
            models_added = len(p.get("models", []))
            break

    return {
        "status": "success",
        "provider": {
            "provider_id": provider_id,
            "status": result.get("status", "unknown"),
            "message": result.get("message", ""),
            "latency_ms": result.get("latency_ms"),
        },
        "models_added": models_added,
        "timestamp": time.time(),
    }


@router.post("/{provider_id}/test")
async def test_provider_credentials(provider_id: str, body: ProviderCredentialInput) -> Dict[str, Any]:
    """Test credentials without storing them."""
    registry = _get_registry()
    providers = {p["provider_id"]: p for p in registry.list_providers()}
    if provider_id not in providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    adapters = getattr(registry, "_adapters", None)
    adapter = adapters.get(provider_id) if adapters else None
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Provider adapter '{provider_id}' not found")

    try:
        result = await adapter.test_credentials(body.credentials)
    except Exception as exc:
        logger.exception("Adapter test_credentials raised for %s", provider_id)
        return {
            "success": False,
            "message": f"Test failed: {exc}",
            "latency_ms": None,
            "error_details": str(exc),
            "models_available": None,
            "timestamp": time.time(),
        }

    return {
        "success": result.success,
        "message": result.message,
        "latency_ms": result.latency_ms,
        "error_details": result.error_details,
        "models_available": result.models_available,
        "timestamp": time.time(),
    }


@router.delete("/{provider_id}/credentials")
async def remove_provider_credentials(provider_id: str) -> Dict[str, Any]:
    """Remove stored credentials for a provider (vault + registry)."""
    vault = _get_vault()
    registry = _get_registry()

    vault.remove(provider_id)
    try:
        registry.remove_credentials(provider_id)
    except ValueError:
        pass  # not in registry — already clean

    return {
        "status": "success",
        "message": f"Credentials for '{provider_id}' removed",
        "timestamp": time.time(),
    }


# ─── Sync ──────────────────────────────────────────────────────────────────

@router.post("/sync")
async def force_sync() -> Dict[str, Any]:
    """Force re-sync ``.env`` + vault → registry. Call after manual ``.env`` edits."""
    bridge = _get_bridge()
    results = bridge.sync_all()
    return {
        "status": "success",
        "results": results,
        "timestamp": time.time(),
    }


@router.post("/refresh")
async def refresh_providers() -> Dict[str, Any]:
    """Legacy alias for ``/sync``. Same effect, simpler payload."""
    bridge = _get_bridge()
    results = bridge.sync_all()
    registry = _get_registry()
    configured = [p for p in registry.list_providers() if p.get("status") == "configured"]
    return {"status": "refreshed", "configured_count": len(configured), "results": results}
