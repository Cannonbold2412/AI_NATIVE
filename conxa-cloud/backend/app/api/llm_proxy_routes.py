"""Metered LLM proxy for the Build Studio desktop app.

Build Studio runs the compiler locally but has no LLM keys. It forwards every
text/vision LLM call here; the cloud holds the provider pool, enforces a
per-org monthly token quota, and records usage for billing/analytics.

Auth: inherits Clerk JWT verification from ProductionRequestMiddleware. These
routes additionally require the ``X-Conxa-Client`` header (the proxy is called
by the desktop backend, never a browser) and reject browsers via that header
rather than CORS.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from conxa_core.config import settings
from app.llm.router import get_router
from app.services import llm_metering
from app.services.entitlements import (
    ALLOWED_USAGE_CLASSES,
    EntitlementError,
    current_entitlements,
    ensure_human_edit_available,
    record_llm_usage,
)
from app.services.saas import Principal, ensure_principal, principal_from_request

router = APIRouter(prefix="/llm/proxy", tags=["llm-proxy"], include_in_schema=False)


class ProxyBody(BaseModel):
    task: str = Field(..., min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    usage_class: str = Field(default="compile", max_length=32)


def _require_studio_client(request: Request) -> None:
    expected = settings.llm_proxy_client_header.strip()
    got = request.headers.get("x-conxa-client", "").strip()
    if not expected or got != expected:
        raise HTTPException(status_code=403, detail="proxy_requires_build_studio_client")


def _principal(request: Request) -> Principal:
    principal = principal_from_request(request)
    ensure_principal(principal)
    return principal


def _meter_and_call(request: Request, body: ProxyBody, *, vision: bool) -> dict[str, Any]:
    _require_studio_client(request)
    principal = _principal(request)
    org_id = principal.workspace_id
    usage_class = str(body.usage_class or "compile").strip()
    if usage_class not in ALLOWED_USAGE_CLASSES:
        raise HTTPException(status_code=400, detail="invalid_usage_class")

    if usage_class == "compile" and llm_metering.quota_exceeded(org_id, settings.llm_proxy_monthly_token_quota):
        raise HTTPException(status_code=429, detail="quota_exceeded")

    input_tokens = llm_metering.estimate_request_tokens(body.payload)
    if usage_class == "human_edit":
        try:
            ensure_human_edit_available(principal, estimated_tokens=input_tokens)
        except EntitlementError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    router_impl = get_router()
    error_detail: list[str] = []
    try:
        if vision:
            result = router_impl.route_vision(
                body.task, body.payload, body.timeout_ms, error_detail=error_detail
            )
        else:
            result = router_impl.route_text(
                body.task, body.payload, body.timeout_ms, error_detail=error_detail
            )
    except RuntimeError as exc:
        # No providers configured — treat as upstream unavailable.
        raise HTTPException(status_code=502, detail=f"llm_unavailable: {exc}") from exc

    if result is None:
        raise HTTPException(
            status_code=502,
            detail={"message": "llm_all_providers_failed", "error_detail": error_detail[:8]},
        )

    output_tokens = llm_metering.estimate_response_tokens(result)
    llm_metering.record_usage(org_id, input_tokens=input_tokens, output_tokens=output_tokens)
    try:
        record_llm_usage(
            principal,
            usage_class=usage_class,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except EntitlementError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="entitlements_unavailable") from exc
    return result


@router.post("/text")
def proxy_text(body: ProxyBody, request: Request) -> dict[str, Any]:
    return _meter_and_call(request, body, vision=False)


@router.post("/vision")
def proxy_vision(body: ProxyBody, request: Request) -> dict[str, Any]:
    return _meter_and_call(request, body, vision=True)


@router.get("/usage")
def proxy_usage(request: Request) -> dict[str, Any]:
    """Current-month usage for the calling org (Build Studio shows this in Settings)."""
    _require_studio_client(request)
    principal = _principal(request)
    org_id = principal.workspace_id
    usage = llm_metering.get_usage(org_id)
    try:
        entitlements = current_entitlements(principal)
    except Exception:
        entitlements = None
    return {"org_id": org_id, "usage": usage, "quota": settings.llm_proxy_monthly_token_quota, "entitlements": entitlements}
