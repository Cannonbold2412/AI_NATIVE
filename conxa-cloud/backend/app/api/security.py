"""Production-facing request middleware: request IDs, body caps, and Clerk auth."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

PUBLIC_PATHS = {
    "/",
    "/health",
    "/api/v1/health",
    "/api/v1/webhooks/stripe",
}

# Runtime telemetry ingestion uses its own package token; tracking reads stay behind Clerk.
PUBLIC_TRACKING_EVENT_PREFIXES = ("/api/tracking/", "/api/v1/tracking/")

# Installer downloads are fetched by end users who have no Clerk account; the
# plugin_id in the path is the only credential and the file is non-sensitive.
PUBLIC_PATH_PREFIXES = (
    "/api/v1/installers/",
    # Build Studio bootstrap and runtime self-updater fetch these before/without Clerk auth
    "/api/v1/updates/",
)


def _request_id(request: Request) -> str:
    rid = request.headers.get("x-request-id", "").strip()
    return rid[:128] if rid else secrets.token_hex(12)


def _is_public_path(path: str, method: str = "GET") -> bool:
    normalized = path.rstrip("/") or "/"
    if normalized in PUBLIC_PATHS:
        return True
    if any(normalized.startswith(p.rstrip("/")) for p in PUBLIC_PATH_PREFIXES):
        return True
    if method.upper() == "POST" and normalized.endswith("/events"):
        return any(normalized.startswith(p) for p in PUBLIC_TRACKING_EVENT_PREFIXES)
    return False


def _bearer_token(request: Request) -> str:
    value = request.headers.get("authorization", "").strip()
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    return token.strip()


def verify_clerk_jwt(token: str) -> dict[str, Any]:
    """Verify a Clerk JWT when SKILL_AUTH_REQUIRED is enabled.

    PyJWT is intentionally imported lazily so local tests do not require the
    optional crypto dependency unless auth verification is actually enabled.
    """

    if not settings.clerk_issuer or not settings.clerk_jwks_url:
        raise HTTPException(status_code=500, detail="clerk_auth_not_configured")
    try:
        import jwt
        from jwt import PyJWKClient
    except Exception as exc:  # pragma: no cover - exercised only in auth deployments
        raise HTTPException(status_code=500, detail="pyjwt_dependency_missing") from exc

    try:
        signing_key = PyJWKClient(settings.clerk_jwks_url).get_signing_key_from_jwt(token)
        options = {"verify_aud": bool(settings.clerk_audience)}
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.clerk_audience or None,
            issuer=settings.clerk_issuer,
            options=options,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid_clerk_token") from exc

    azp_values = settings.clerk_authorized_party_values
    if azp_values and payload.get("azp") not in azp_values:
        raise HTTPException(status_code=403, detail="invalid_authorized_party")
    return dict(payload)


class ProductionRequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        rid = _request_id(request)
        request.state.request_id = rid

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
            except ValueError:
                size = 0
            if size > settings.max_json_body_bytes:
                return JSONResponse(
                    {"detail": "request_body_too_large", "request_id": rid},
                    status_code=413,
                    headers={"x-request-id": rid},
                )

        is_public = _is_public_path(request.url.path, request.method)
        if settings.auth_required and not is_public:
            try:
                claims = verify_clerk_jwt(_bearer_token(request))
            except HTTPException as exc:
                return JSONResponse(
                    {"detail": exc.detail, "request_id": rid},
                    status_code=exc.status_code,
                    headers={"x-request-id": rid},
                )
            request.state.auth = {
                "subject": claims.get("sub"),
                "org_id": claims.get("org_id") or claims.get("orgid"),
                "claims": claims,
            }
            request.state.workspace_id = (
                claims.get("org_id") or claims.get("orgid") or claims.get("sub")
            )

        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response
