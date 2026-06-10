"""Razorpay subscription endpoints — plans, subscriptions, webhooks, and verification."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import razorpay
from fastapi import APIRouter, Depends, HTTPException, Request

from conxa_core.config import settings
from conxa_core.db import db_get, db_set
from app.services.rbac import require_admin
from app.services.saas import Principal, ensure_principal, principal_from_request, upsert_billing

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


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
        "amount": 49900,  # 499 INR in paise
        "currency": "INR",
        "period": "monthly",
        "features": ["3 seats", "3 installer slots", "300 compile credits/month", "10M Human Edit tokens/month"],
    },
    "pro": {
        "name": "Pro",
        "amount": 99900,  # 999 INR in paise
        "currency": "INR",
        "period": "monthly",
        "features": ["10 seats", "10 installer slots", "1000 compile credits/month", "50M Human Edit tokens/month"],
    },
}


def _normalize_tier(tier: str) -> str:
    value = str(tier or "").strip().lower()
    return "starter" if value == "basic" else value


def _client() -> razorpay.Client:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=500, detail="Razorpay credentials not configured")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


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
    store = _read_plan_store()
    if tier == "starter" and "starter" not in store and "basic" in store:
        store["starter"] = store["basic"]
        _write_plan_store(store)
    if tier in store:
        return store[tier]
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
        store[tier] = plan_id
        _write_plan_store(store)
        return plan_id
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed_to_create_plan: {exc!s}") from exc


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
                "amount": 499,
                "currency": "INR",
                "period": "monthly",
                "features": TIER_INFO["starter"]["features"],
            },
            {
                "tier": "pro",
                "name": TIER_INFO["pro"]["name"],
                "amount": 999,
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
            "total_count": 0,  # 0 = infinite
            "quantity": 1,
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
        raise HTTPException(status_code=500, detail=f"subscription_error: {exc!s}") from exc


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
        tier = None
        for t, plan_id in _read_plan_store().items():
            if subscription.get("plan_id") == plan_id:
                tier = _normalize_tier(t)
                break
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
        raise HTTPException(status_code=500, detail=f"verify_error: {exc!s}") from exc


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
            tier = None
            for t, plan_id in _read_plan_store().items():
                if subscription.get("plan_id") == plan_id:
                    tier = _normalize_tier(t)
                    break
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
