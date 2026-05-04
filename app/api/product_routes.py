"""SaaS product API: identity, workspaces, dashboard, billing, releases, audit."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.services.saas import (
    Principal,
    add_audit_event,
    audit_events_for,
    billing_for,
    dashboard_for,
    ensure_principal,
    principal_from_request,
    release_for,
    update_release,
    upsert_billing,
    usage_for,
)
from app.storage.skill_packages import bundle_root_dir

router = APIRouter(tags=["product"])


def current_principal(request: Request) -> Principal:
    principal = principal_from_request(request)
    ensure_principal(principal)
    return principal


class ReleasePatchBody(BaseModel):
    state: str | None = Field(default=None, pattern="^(draft|published|archived)$")
    version: str | None = Field(default=None, min_length=1, max_length=64)
    release_notes: str | None = Field(default=None, max_length=20_000)


class PublishBody(BaseModel):
    version: str | None = Field(default=None, min_length=1, max_length=64)
    release_notes: str = Field(default="", max_length=20_000)


def _require_bundle(bundle_slug: str) -> None:
    root = bundle_root_dir(bundle_slug)
    if root is None or not root.is_dir():
        raise HTTPException(status_code=404, detail="package_bundle_not_found")


@router.get("/me")
def get_me(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    return {
        "user": principal.public_user(),
        "workspace": principal.public_workspace(),
        "auth_required": settings.auth_required,
    }


@router.get("/workspaces/current")
def get_current_workspace(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    return {"workspace": principal.public_workspace()}


@router.get("/dashboard")
def get_dashboard(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    return dashboard_for(principal)


@router.get("/usage")
def get_usage(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    return usage_for(principal)


@router.get("/billing/subscription")
def get_subscription(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    return {"subscription": billing_for(principal)}


def _stripe_client() -> Any:
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="stripe_not_configured")
    try:
        import stripe
    except Exception as exc:  # pragma: no cover - optional deployment dependency
        raise HTTPException(status_code=500, detail="stripe_dependency_missing") from exc
    stripe.api_key = settings.stripe_secret_key
    return stripe


@router.post("/billing/checkout")
def post_checkout(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    if not settings.stripe_price_id:
        raise HTTPException(status_code=503, detail="stripe_price_not_configured")
    stripe = _stripe_client()
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
            success_url=f"{settings.app_url.rstrip('/')}/billing?checkout=success",
            cancel_url=f"{settings.app_url.rstrip('/')}/billing?checkout=cancelled",
            client_reference_id=principal.workspace_id,
            metadata={"workspace_id": principal.workspace_id},
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"stripe_checkout_failed: {exc!s}") from exc
    add_audit_event(principal, "billing_checkout_created", resource_type="billing")
    return {"url": session.url}


@router.post("/billing/portal")
def post_portal(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    billing = billing_for(principal)
    customer_id = billing.get("customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="stripe_customer_missing")
    stripe = _stripe_client()
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{settings.app_url.rstrip('/')}/billing",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"stripe_portal_failed: {exc!s}") from exc
    add_audit_event(principal, "billing_portal_created", resource_type="billing")
    return {"url": session.url}


@router.post("/webhooks/stripe")
async def post_stripe_webhook(request: Request) -> dict[str, Any]:
    payload = await request.body()
    event: dict[str, Any]
    if settings.stripe_webhook_secret:
        stripe = _stripe_client()
        signature = request.headers.get("stripe-signature", "")
        try:
            event_obj = stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="invalid_stripe_webhook") from exc
        event = dict(event_obj)
    else:
        try:
            event = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="invalid_json_webhook") from exc

    event_type = str(event.get("type") or "")
    obj = ((event.get("data") or {}).get("object") or {}) if isinstance(event.get("data"), dict) else {}
    metadata = obj.get("metadata") if isinstance(obj, dict) else {}
    workspace_id = metadata.get("workspace_id") if isinstance(metadata, dict) else None
    if workspace_id and event_type in {"checkout.session.completed", "customer.subscription.updated"}:
        upsert_billing(
            str(workspace_id),
            {
                "plan": "pro",
                "status": "active",
                "customer_id": obj.get("customer") if isinstance(obj, dict) else None,
                "subscription_id": obj.get("subscription") if isinstance(obj, dict) else None,
            },
        )
    return {"received": True}


@router.post("/packages/bundles/{bundle_slug}/publish")
def publish_bundle(
    bundle_slug: str,
    body: PublishBody,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    _require_bundle(bundle_slug)
    previous = release_for(principal, bundle_slug)
    release = update_release(
        principal,
        bundle_slug,
        {
            "state": "published",
            "version": body.version or previous.get("version") or "0.1.0",
            "release_notes": body.release_notes,
            "published_by": principal.user_id,
            "published_at": time.time(),
            "archived_at": None,
        },
    )
    return {"release": release}


@router.patch("/packages/bundles/{bundle_slug}/release")
def patch_bundle_release(
    bundle_slug: str,
    body: ReleasePatchBody,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    _require_bundle(bundle_slug)
    patch = body.model_dump(exclude_none=True)
    if patch.get("state") == "published":
        patch.setdefault("published_by", principal.user_id)
        patch.setdefault("published_at", time.time())
        patch.setdefault("archived_at", None)
    if patch.get("state") == "archived":
        patch.setdefault("archived_at", time.time())
    release = update_release(principal, bundle_slug, patch)
    return {"release": release}


@router.get("/packages/bundles/{bundle_slug}/release")
def get_bundle_release(
    bundle_slug: str,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    _require_bundle(bundle_slug)
    return {"release": release_for(principal, bundle_slug)}


@router.get("/audit-events")
def list_audit_events(
    limit: int = 100,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    return {"audit_events": audit_events_for(principal, limit=limit)}
