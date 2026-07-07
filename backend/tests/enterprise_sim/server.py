"""Enterprise-gateway simulator server (dev / test tooling only).

Not shipped as part of the runtime. Used to exercise the
enterprise-gateway provider adapter end-to-end without hitting a real
identity provider. Mimics the wire protocol of an enterprise LLM
gateway that requires a
2-stage auth flow (identity provider password grant → session-JWT
exchange → OpenAI-compatible completions API) and forwards actual
chat completions to the Azure OpenAI deployment configured in
``backend/.env``.

Endpoints:

* ``POST /oauth2/token``                                  — stage-1 access token
* ``POST /api/auth/v1/backend-tokens/adfs/session-jwt``   — stage-2 session JWT
* ``GET  /v1/models``                                     — OpenAI-compat models list
* ``POST /v1/chat/completions``                           — OpenAI-compat completions (forwarded to Azure)
* ``GET  /healthz``                                       — liveness / config summary

The server issues opaque tokens (``sim-access-…`` / ``sim-session-…``)
with configurable TTLs and validates every subsequent header against
its in-memory token store. On expiry it returns HTTP 401 so the
adapter's refresh-and-retry loop can be exercised.

Tunables (all env vars, all optional):

    ENTERPRISE_SIM_HOST                    (default 127.0.0.1)
    ENTERPRISE_SIM_PORT                    (default 9099)
    ENTERPRISE_SIM_USERNAME                (default sim-user; must match caller)
    ENTERPRISE_SIM_PASSWORD                (default sim-password; must match caller)
    ENTERPRISE_SIM_CONSUMER_APPLICATION    (default mars-newsletter-sim)
    ENTERPRISE_SIM_ACCESS_TTL_SECONDS      (default 3600)
    ENTERPRISE_SIM_SESSION_TTL_SECONDS     (default 900)
    ENTERPRISE_SIM_FAIL_EVERY_N_CALLS      (default 0 = never; if >0, every Nth
                                           chat/models call returns 401 to
                                           exercise the refresh path)
    ENTERPRISE_SIM_LOG_LEVEL               (default info)

Azure forwarding uses the same variables NewsLetter itself consumes so
the simulator inherits whatever Azure deployment the backend has been
configured against:

    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_ENDPOINT
    AZURE_OPENAI_DEPLOYMENT
    AZURE_OPENAI_API_VERSION   (default 2024-12-01-preview)

Usage::

    python -m tests.enterprise_sim.server
    # or
    python tests/enterprise_sim/server.py
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("enterprise_sim")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("bad int for %s=%r — using default %d", name, raw, default)
        return default


@dataclass
class SimConfig:
    host: str = field(default_factory=lambda: os.getenv("ENTERPRISE_SIM_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("ENTERPRISE_SIM_PORT", 9099))
    username: str = field(default_factory=lambda: os.getenv("ENTERPRISE_SIM_USERNAME", "sim-user"))
    password: str = field(default_factory=lambda: os.getenv("ENTERPRISE_SIM_PASSWORD", "sim-password"))
    consumer_application: str = field(
        default_factory=lambda: os.getenv("ENTERPRISE_SIM_CONSUMER_APPLICATION", "mars-newsletter-sim")
    )
    access_ttl_seconds: int = field(default_factory=lambda: _env_int("ENTERPRISE_SIM_ACCESS_TTL_SECONDS", 3600))
    session_ttl_seconds: int = field(default_factory=lambda: _env_int("ENTERPRISE_SIM_SESSION_TTL_SECONDS", 900))
    fail_every_n_calls: int = field(default_factory=lambda: _env_int("ENTERPRISE_SIM_FAIL_EVERY_N_CALLS", 0))

    # Azure backend (reused from NewsLetter's own env)
    azure_api_key: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_API_KEY", ""))
    azure_endpoint: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT", ""))
    azure_deployment: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT", ""))
    azure_api_version: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    )


# ---------------------------------------------------------------------------
# Token store
# ---------------------------------------------------------------------------

@dataclass
class _Token:
    value: str
    expires_at: float
    subject: str


class TokenStore:
    """In-memory bag of issued tokens with TTL enforcement."""

    def __init__(self) -> None:
        self._access: Dict[str, _Token] = {}
        self._session: Dict[str, _Token] = {}
        self._call_counter = 0

    # -- issue ------------------------------------------------------------
    def issue_access(self, subject: str, ttl: int) -> _Token:
        tok = _Token(value=f"sim-access-{uuid.uuid4().hex}", expires_at=time.time() + ttl, subject=subject)
        self._access[tok.value] = tok
        return tok

    def issue_session(self, subject: str, ttl: int) -> _Token:
        tok = _Token(value=f"sim-session-{uuid.uuid4().hex}", expires_at=time.time() + ttl, subject=subject)
        self._session[tok.value] = tok
        return tok

    # -- validate ---------------------------------------------------------
    def validate_access(self, header_value: str) -> Optional[_Token]:
        if not header_value:
            return None
        token = header_value.removeprefix("Bearer ").strip()
        tok = self._access.get(token)
        if not tok or tok.expires_at < time.time():
            return None
        return tok

    def validate_session(self, header_value: str) -> Optional[_Token]:
        if not header_value:
            return None
        # Session header is passed verbatim, no "Bearer " prefix.
        tok = self._session.get(header_value.strip())
        if not tok or tok.expires_at < time.time():
            return None
        return tok

    # -- diagnostics ------------------------------------------------------
    def next_call_should_fail(self, fail_every_n: int) -> bool:
        self._call_counter += 1
        return fail_every_n > 0 and (self._call_counter % fail_every_n == 0)

    def stats(self) -> Dict[str, int]:
        now = time.time()
        return {
            "issued_access_tokens": len(self._access),
            "issued_session_tokens": len(self._session),
            "live_access_tokens": sum(1 for t in self._access.values() if t.expires_at >= now),
            "live_session_tokens": sum(1 for t in self._session.values() if t.expires_at >= now),
            "requests_served": self._call_counter,
        }


# ---------------------------------------------------------------------------
# Azure forwarding
# ---------------------------------------------------------------------------

def _forward_to_azure(config: SimConfig, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send the OpenAI-compat payload to Azure OpenAI, return the response body.

    Uses the ``AzureOpenAI`` client so the SDK handles the api-version / deployment
    URL rewriting. The response is converted back to a plain dict so downstream
    consumers see a normal OpenAI JSON body.
    """
    if not (config.azure_api_key and config.azure_endpoint and config.azure_deployment):
        raise HTTPException(
            status_code=503,
            detail="Enterprise sim has no Azure OpenAI backend configured (set AZURE_OPENAI_*).",
        )
    try:
        from openai import AzureOpenAI  # type: ignore
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"openai SDK not installed: {exc}")

    client = AzureOpenAI(
        api_key=config.azure_api_key,
        azure_endpoint=config.azure_endpoint,
        api_version=config.azure_api_version,
    )

    # Ignore the caller-supplied model name — always route to our
    # configured Azure deployment.
    call_kwargs = dict(payload)
    call_kwargs.pop("model", None)
    call_kwargs["model"] = config.azure_deployment

    # OpenAI-compat clients still send ``max_tokens`` but newer Azure API
    # versions (2024-12-01-preview and later on the gpt-4o family) reject
    # it in favour of ``max_completion_tokens``. Translate on the way in so
    # the simulator stays a drop-in OpenAI-compat surface.
    if "max_tokens" in call_kwargs and "max_completion_tokens" not in call_kwargs:
        call_kwargs["max_completion_tokens"] = call_kwargs.pop("max_tokens")

    try:
        resp = client.chat.completions.create(**call_kwargs)
    except Exception as exc:
        logger.exception("azure forwarding failed")
        raise HTTPException(status_code=502, detail=f"Azure backend error: {exc}")

    # Convert the pydantic response to a plain dict.
    if hasattr(resp, "model_dump"):
        return resp.model_dump()
    if hasattr(resp, "dict"):
        return resp.dict()  # type: ignore[no-any-return]
    return json.loads(json.dumps(resp, default=str))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def create_app(config: Optional[SimConfig] = None) -> FastAPI:
    config = config or SimConfig()
    store = TokenStore()
    app = FastAPI(
        title="Enterprise LLM Gateway (simulator)",
        version="0.1.0",
        description=(
            "Local simulator that mimics an enterprise LLM gateway's 2-stage "
            "auth flow and forwards completions to Azure OpenAI."
        ),
    )

    # ------------- diagnostics ---------------------------------------
    @app.get("/healthz")
    async def healthz() -> Dict[str, Any]:
        return {
            "status": "ok",
            "azure_backend_configured": bool(
                config.azure_api_key and config.azure_endpoint and config.azure_deployment
            ),
            "expected_username": config.username,
            "expected_consumer_application": config.consumer_application,
            "access_ttl_seconds": config.access_ttl_seconds,
            "session_ttl_seconds": config.session_ttl_seconds,
            "fail_every_n_calls": config.fail_every_n_calls,
            "stats": store.stats(),
        }

    # ------------- stage 1: password grant ---------------------------
    async def _stage1_common(
        grant_type: str,
        username: str,
        password: str,
        client_id: Optional[str],
    ) -> Dict[str, Any]:
        if grant_type != "password":
            # We only simulate the password grant flow. Other grant types
            # can be added if the adapter's tests need them.
            raise HTTPException(status_code=400, detail=f"unsupported grant_type: {grant_type}")
        # Constant-time credential compare to avoid trivial side channels.
        u_ok = secrets.compare_digest(username or "", config.username)
        p_ok = secrets.compare_digest(password or "", config.password)
        if not (u_ok and p_ok):
            raise HTTPException(status_code=401, detail="invalid_credentials")
        token = store.issue_access(subject=username, ttl=config.access_ttl_seconds)
        logger.info("stage-1 issued access token for %s (ttl=%ds)", username, config.access_ttl_seconds)
        return {
            "access_token": token.value,
            "token_type": "Bearer",
            "expires_in": config.access_ttl_seconds,
            "resource": "sim",
            "client_id": client_id or "",
        }

    @app.post("/oauth2/token")
    async def oauth2_token(
        request: Request,
        grant_type: Optional[str] = Form(None),
        username: Optional[str] = Form(None),
        password: Optional[str] = Form(None),
        client_id: Optional[str] = Form(None),
        resource: Optional[str] = Form(None),
    ) -> Dict[str, Any]:
        # Accept both form-encoded (default) and JSON payloads so we can
        # exercise both ENTERPRISE_LLM_TOKEN_ENCODING modes.
        if grant_type is None:
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                body = {}
            grant_type = body.get("grant_type") or "password"
            username = body.get("username")
            password = body.get("password")
            client_id = body.get("client_id")
            resource = body.get("resource")
        return await _stage1_common(grant_type or "password", username or "", password or "", client_id)

    # ------------- stage 2: session-JWT exchange ---------------------
    @app.post("/api/auth/v1/backend-tokens/adfs/session-jwt")
    async def session_jwt(
        request: Request,
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        tok = store.validate_access(authorization or "")
        if tok is None:
            raise HTTPException(status_code=401, detail="stage-1 token missing / invalid / expired")
        # Body is optional and freeform — we accept anything, just log it.
        try:
            body = await request.json()
        except Exception:
            body = {}
        session_tok = store.issue_session(subject=tok.subject, ttl=config.session_ttl_seconds)
        logger.info(
            "stage-2 issued session token for %s (ttl=%ds) body_keys=%s",
            tok.subject, config.session_ttl_seconds, list(body.keys()) if isinstance(body, dict) else "?",
        )
        return {
            "token": session_tok.value,
            "expires_in": config.session_ttl_seconds,
            "subject": tok.subject,
        }

    # ------------- shared header validation --------------------------
    def _validate_gateway_headers(
        authorization: Optional[str],
        session_hdr: Optional[str],
        consumer_hdr: Optional[str],
    ) -> None:
        access_tok = store.validate_access(authorization or "")
        if access_tok is None:
            raise HTTPException(status_code=401, detail="access token missing / expired")
        session_tok = store.validate_session(session_hdr or "")
        if session_tok is None:
            raise HTTPException(status_code=401, detail="session token missing / expired")
        if not consumer_hdr or consumer_hdr != config.consumer_application:
            raise HTTPException(
                status_code=403,
                detail=f"consumer application mismatch (expected {config.consumer_application!r}, got {consumer_hdr!r})",
            )

    def _maybe_force_401() -> None:
        if store.next_call_should_fail(config.fail_every_n_calls):
            logger.warning("forcing 401 to exercise refresh path")
            raise HTTPException(status_code=401, detail="simulated periodic 401")

    # ------------- OpenAI-compat models ------------------------------
    @app.get("/v1/models")
    async def list_models(
        authorization: Optional[str] = Header(None),
        x_authorization_session: Optional[str] = Header(None, convert_underscores=True),
        x_consumer_application: Optional[str] = Header(None, convert_underscores=True),
    ) -> Dict[str, Any]:
        _validate_gateway_headers(authorization, x_authorization_session, x_consumer_application)
        _maybe_force_401()
        return {
            "object": "list",
            "data": [
                {"id": "gpt-4o", "object": "model", "owned_by": "enterprise-sim"},
                {"id": "gpt-4o-mini", "object": "model", "owned_by": "enterprise-sim"},
                {"id": "gpt-4.1", "object": "model", "owned_by": "enterprise-sim"},
            ],
        }

    # ------------- OpenAI-compat chat completions --------------------
    @app.post("/v1/chat/completions")
    async def chat_completions(
        request: Request,
        authorization: Optional[str] = Header(None),
        x_authorization_session: Optional[str] = Header(None, convert_underscores=True),
        x_consumer_application: Optional[str] = Header(None, convert_underscores=True),
    ) -> JSONResponse:
        _validate_gateway_headers(authorization, x_authorization_session, x_consumer_application)
        _maybe_force_401()
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON body: {exc}")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        response_body = _forward_to_azure(config, payload)
        # Sanitise the outgoing model name back to what the caller asked for
        # so the OpenAI SDK on the caller's side doesn't get surprised by the
        # Azure deployment name.
        caller_model = payload.get("model")
        if caller_model and isinstance(response_body, dict):
            response_body["model"] = caller_model
        return JSONResponse(content=response_body)

    return app


def main() -> None:
    logging.basicConfig(
        level=os.getenv("ENTERPRISE_SIM_LOG_LEVEL", "info").upper(),
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    )
    config = SimConfig()
    logger.info(
        "starting enterprise sim on http://%s:%d (azure backend=%s deployment=%s)",
        config.host, config.port,
        "yes" if config.azure_api_key and config.azure_endpoint else "no",
        config.azure_deployment or "<unset>",
    )
    import uvicorn  # local import so `import server` is cheap for tests

    uvicorn.run(create_app(config), host=config.host, port=config.port, log_level=os.getenv("ENTERPRISE_SIM_LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
