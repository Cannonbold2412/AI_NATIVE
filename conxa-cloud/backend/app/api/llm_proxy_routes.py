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

from app.config import settings
from app.llm.router import get_router
from app.services import llm_metering
from app.services.saas import principal_from_request

router = APIRouter(prefix="/llm/proxy", tags=["llm-proxy"], include_in_schema=False)


class ProxyBody(BaseModel):
    task: str = Field(..., min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)


def _require_studio_client(request: Request) -> None:
    expected = settings.llm_proxy_client_header.strip()
    got = request.headers.get("x-conxa-client", "").strip()
    if not expected or got != expected:
        raise HTTPException(status_code=403, detail="proxy_requires_build_studio_client")


def _org_id(request: Request) -> str:
    principal = principal_from_request(request)
    return principal.workspace_id


def _meter_and_call(request: Request, body: ProxyBody, *, vision: bool) -> dict[str, Any]:
    _require_studio_client(request)
    org_id = _org_id(request)

    if llm_metering.quota_exceeded(org_id, settings.llm_proxy_monthly_token_quota):
        raise HTTPException(status_code=429, detail="quota_exceeded")

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

    llm_metering.record_usage(
        org_id,
        input_tokens=llm_metering.estimate_request_tokens(body.payload),
        output_tokens=llm_metering.estimate_response_tokens(result),
    )
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
    org_id = _org_id(request)
    usage = llm_metering.get_usage(org_id)
    return {
        "org_id": org_id,
        "usage": usage,
        "quota": settings.llm_proxy_monthly_token_quota,
    }
