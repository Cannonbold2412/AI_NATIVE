"""Razorpay subscription endpoints — plans, subscriptions, webhooks, and verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path
from typing import Any

import razorpay
from fastapi import APIRouter, Depends, HTTPException, Request

from conxa_core.config import settings
from conxa_core.db import db_get, db_set
from app.services.rbac import require_admin
from app.services.saas import Principal, ensure_principal, principal_from_request, upsert_billing

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

RAZORPAY_MONTHLY_TOTAL_COUNT = 1200


def current_principal(request: Request) -> Principal:
    principal = principal_from_request(request)
    ensure_principal(principal)
    return principal


TIER_INFO = {
    "free": {
        "name": "Free",
        "amount": 0,
        "currency": "INR",
        "period": None,
        "features": ["1 seat", "1 installer slot", "50 compile credits/month", "1M Human Edit tokens/month"],
    },
    "starter": {
        "name": "Starter",
        "amount": 2999900,
        "currency": "INR",
        "period": "monthly",
        "features": ["3 seats", "3 installer slots", "300 compile credits/month", "10M Human Edit tokens/month"],
    },
    "pro": {
        "name": "Pro",
        "amount": 7999900,
        "currency": "INR",
        "period": "monthly",
        "features": ["10 seats", "10 installer slots", "1000 compile credits/month", "50M Human Edit tokens/month"],
    },
}


def _normalize_tier(tier: str) -> str:
    value = str(tier or "").strip().lower()
    return "starter" if value == "basic" else value


def _plan_store_key(tier: str) -> str:
    info = TIER_INFO[tier]
    return f"{tier}:{info['currency']}:{info['amount']}"


def _tier_from_plan_store_key(key: str) -> str:
    return _normalize_tier(str(key).split(":", 1)[0])


def _tier_for_plan_id(plan_id: str) -> str | None:
    configured = {
        "starter": settings.razorpay_starter_plan_id.strip(),
        "pro": settings.razorpay_pro_plan_id.strip(),
    }
    for tier, configured_plan_id in configured.items():
        if plan_id and plan_id == configured_plan_id:
            return tier
    for key, stored_plan_id in _read_plan_store().items():
        if plan_id == stored_plan_id:
            tier = _tier_from_plan_store_key(key)
            if tier in TIER_INFO and tier != "free":
                return tier
    return None


def _exception_detail(exc: Exception) -> str:
    message = str(exc).strip()
    if message and message.lower() != "none":
        return message
    args = [str(arg).strip() for arg in getattr(exc, "args", ()) if arg is not None and str(arg).strip()]
    if args:
        return "; ".join(args)
    return exc.__class__.__name__


def _client() -> razorpay.Client:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=500, detail="Razorpay credentials not configured")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


def _configured_plan_id(tier: str) -> str:
    if tier == "starter":
        return settings.razorpay_starter_plan_id.strip()
    if tier == "pro":
        return settings.razorpay_pro_plan_id.strip()
    return ""


def _plan_store_path() -> Path:
    return settings.data_dir / "razorpay_plans.json"


def _read_plan_store() -> dict[str, str]:
    data = db_get("razorpay", "plans")
    if data is not None:
        return data
    path = _plan_store_path()
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _write_plan_store(store: dict[str, str]) -> None:
    db_set("razorpay", "plans", store)
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _plan_store_path().write_text(json.dumps(store, indent=2))
    except OSError:
        pass


def _ensure_plan(tier: str) -> str:
    """Create or retrieve Razorpay plan ID for tier. Returns plan_id."""
    tier = _normalize_tier(tier)
    if tier not in TIER_INFO or tier == "free":
        raise HTTPException(status_code=400, detail=f"invalid tier: {tier}")
    configured_plan_id = _configured_plan_id(tier)
    if configured_plan_id:
        return configured_plan_id
    if settings.auth_required:
        raise HTTPException(
            status_code=500,
            detail=f"Razorpay {tier} plan ID not configured",
        )
    store = _read_plan_store()
    plan_key = _plan_store_key(tier)
    if plan_key in store:
        return store[plan_key]
    info = TIER_INFO[tier]
    try:
        plan = _client().plan.create({  # type: ignore[attr-defined,union-attr]
            "period": info["period"],
            "interval": 1,
            "item": {
                "name": f"Conxa {info['name']} Plan",
                "amount": info["amount"],
                "currency": info["currency"],
                "description": f"{info['name']} subscription - ₹{info['amount'] // 100}/month",
            },
        })
        plan_id = plan["id"]
        store[plan_key] = plan_id
        _write_plan_store(store)
        return plan_id
    except HTTPException as exc:
        logger.error(
            "razorpay_plan_create_config_error tier=%s plan_key=%s amount=%s currency=%s detail=%s",
            tier,
            plan_key,
            info["amount"],
            info["currency"],
            exc.detail,
        )
        raise
    except Exception as exc:
        detail = _exception_detail(exc)
        logger.exception(
            "razorpay_plan_create_failed tier=%s plan_key=%s amount=%s currency=%s error=%s",
            tier,
            plan_key,
            info["amount"],
            info["currency"],
            detail,
        )
        raise HTTPException(status_code=500, detail=f"failed_to_create_plan: {detail}") from exc


@router.get("/plans")
def list_plans() -> dict[str, Any]:
    """Return available subscription tiers with features and pricing."""
    return {
        "plans": [
            {
                "tier": "free",
                "name": TIER_INFO["free"]["name"],
                "amount": 0,
                "currency": "INR",
                "period": None,
                "features": TIER_INFO["free"]["features"],
            },
            {
                "tier": "starter",
                "name": TIER_INFO["starter"]["name"],
                "amount": TIER_INFO["starter"]["amount"] // 100,
                "currency": "INR",
                "period": "monthly",
                "features": TIER_INFO["starter"]["features"],
            },
            {
                "tier": "pro",
                "name": TIER_INFO["pro"]["name"],
                "amount": TIER_INFO["pro"]["amount"] // 100,
                "currency": "INR",
                "period": "monthly",
                "features": TIER_INFO["pro"]["features"],
            },
        ]
    }


@router.post("/create")
async def create_subscription(body: dict[str, str], principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    """Create a Razorpay subscription for a tier. Returns subscription_id."""
    require_admin(principal)
    tier = _normalize_tier(body.get("tier", ""))
    if tier not in ["starter", "pro"]:
        raise HTTPException(status_code=400, detail="tier must be 'starter' or 'pro'")
    try:
        plan_id = _ensure_plan(tier)
        info = TIER_INFO[tier]
        subscription = _client().subscription.create({  # type: ignore[attr-defined,union-attr]
            "plan_id": plan_id,
            "total_count": RAZORPAY_MONTHLY_TOTAL_COUNT,
            "quantity": 1,
            "notes": {
                "workspace_id": principal.workspace_id,
                "tier": tier,
            },
        })
        return {
            "subscription_id": subscription["id"],
            "plan_id": plan_id,
            "amount": info["amount"],
            "currency": info["currency"],
            "tier": tier,
        }
    except HTTPException:
        raise
    except Exception as exc:
        detail = _exception_detail(exc)
        logger.exception(
            "razorpay_subscription_create_failed workspace_id=%s tier=%s error=%s",
            principal.workspace_id,
            tier,
            detail,
        )
        raise HTTPException(status_code=500, detail=f"subscription_error: {detail}") from exc


@router.post("/verify")
async def verify_subscription(body: dict[str, str], principal: Principal = Depends(current_principal)) -> dict[str, bool]:
    """Verify subscription payment signature and update billing record."""
    payment_id = body.get("razorpay_payment_id", "")
    subscription_id = body.get("razorpay_subscription_id", "")
    signature = body.get("razorpay_signature", "")
    if not all([payment_id, subscription_id, signature]):
        raise HTTPException(status_code=400, detail="missing_fields")
    if not settings.razorpay_key_secret:
        raise HTTPException(status_code=500, detail="Razorpay secret not configured")
    message = f"{payment_id}|{subscription_id}"
    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="signature_mismatch")
    try:
        subscription = _client().subscription.fetch(subscription_id)  # type: ignore[attr-defined,union-attr]
        tier = _tier_for_plan_id(str(subscription.get("plan_id") or ""))
        if not tier:
            raise HTTPException(status_code=400, detail="unknown_plan")
        upsert_billing(principal.workspace_id, {
            "plan": tier,
            "status": "active",
            "subscription_id": subscription_id,
        })
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"verify_error: {_exception_detail(exc)}") from exc


@router.post("/webhooks/razorpay")
async def handle_razorpay_webhook(request: Request) -> dict[str, bool]:
    """Handle Razorpay webhook events for subscriptions."""
    body = await request.body()
    if settings.razorpay_webhook_secret:
        signature = request.headers.get("x-razorpay-signature", "")
        expected = hmac.new(
            settings.razorpay_webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=400, detail="invalid_signature")
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_json") from None
    event_type = event.get("event", "")
    payload = event.get("payload", {}).get("subscription", {})
    subscription_id = payload.get("id", "")
    if not subscription_id:
        return {"received": True}
    if event_type in ["subscription.activated", "subscription.charged"]:
        try:
            subscription = _client().subscription.fetch(subscription_id)  # type: ignore[attr-defined,union-attr]
            tier = _tier_for_plan_id(str(subscription.get("plan_id") or ""))
            if tier:
                workspace_id = payload.get("notes", {}).get("workspace_id", "")
                if workspace_id:
                    upsert_billing(workspace_id, {"plan": tier, "status": "active"})
        except Exception:
            pass
    elif event_type == "subscription.cancelled":
        try:
            workspace_id = payload.get("notes", {}).get("workspace_id", "")
            if workspace_id:
                upsert_billing(workspace_id, {"plan": "free", "status": "inactive"})
        except Exception:
            pass
    return {"received": True}
