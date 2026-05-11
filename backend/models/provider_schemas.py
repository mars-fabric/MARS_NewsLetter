"""Pydantic schemas for the Provider Management API endpoints.

Mirrors ``MARS-PaperPulse/backend/models/provider_schemas.py``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProviderCredentialInput(BaseModel):
    """Input for storing or testing credentials."""
    credentials: Dict[str, str] = Field(
        ..., description="Map of credential field name to value"
    )


class ProviderTestResponse(BaseModel):
    """Response for credential test operations."""
    success: bool
    message: str
    latency_ms: Optional[float] = None
    error_details: Optional[str] = None
    models_available: Optional[List[str]] = None


class ProviderStatusResponse(BaseModel):
    """Single provider status (slim summary)."""
    provider_id: str
    display_name: str
    status: str
    models_count: int = 0


class ProviderCredentialFieldSchema(BaseModel):
    """Schema for a single credential field (sent to the frontend)."""
    name: str
    display_name: str
    description: str
    required: bool = True
    field_type: str = "password"
    placeholder: str = ""
    validation_pattern: str = ""
    options: List[Dict[str, Any]] = Field(default_factory=list)
    has_value: bool = False
    masked_value: str = ""
