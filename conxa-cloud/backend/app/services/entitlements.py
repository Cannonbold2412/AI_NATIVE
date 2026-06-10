"""Workspace entitlements, monthly usage meters, and quota reservations."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

from sqlalchemy import text

from conxa_core.config import settings
from conxa_core.db import _get_engine, db_get, db_list, db_set  # type: ignore[attr-defined]
from conxa_core.storage.plugin_store import list_plugins
from app.services.saas import Principal, billing_for, membership_count_for

USAGE_NS = "entitlement_usage"
RESERVATION_NS = "compile_reservations"

ALLOWED_USAGE_CLASSES = {"compile", "human_edit"}

PLAN_LIMITS: dict[str, dict[str, int | None]] = {
    "free": {
        "seats": 1,
        "installer_slots": 1,
        "compile_credits": 50,
        "human_edit_tokens": 1_000_000,
    },
    "starter": {
        "seats": 3,
        "installer_slots": 3,
        "compile_credits": 300,
        "human_edit_tokens": 10_000_000,
    },
    "pro": {
        "seats": 10,
        "installer_slots": 10,
        "compile_credits": 1_000,
        "human_edit_tokens": 50_000_000,
    },
    # Enterprise workspaces must carry explicit overrides in billing metadata.
    "enterprise": {
        "seats": 0,
        "installer_slots": 0,
        "compile_credits": 0,
        "human_edit_tokens": 0,
    },
    "development": {
        "seats": None,
        "installer_slots": None,
        "compile_credits": None,
        "human_edit_tokens": None,
    },
}

_lock = threading.RLock()


class EntitlementError(Exception):
    def __init__(self, code: str, status_code: int = 403) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class _FileKvStore:
    def get(self, namespace: str, key: str) -> Any | None:
        return db_get(namespace, key)

    def set(self, namespace: str, key: str, data: Any) -> None:
        db_set(namespace, key, data)

    def list(self, namespace: str) -> list[Any]:
        return db_list(namespace)


class _SqlKvStore:
    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def get(self, namespace: str, key: str) -> Any | None:
        row = self.conn.execute(
            text("SELECT data FROM kv_store WHERE namespace = :ns AND key = :key"),
            {"ns": namespace, "key": key},
        ).fetchone()
        return row[0] if row else None

    def set(self, namespace: str, key: str, data: Any) -> None:
        self.conn.execute(
            text(
                """
                INSERT INTO kv_store (namespace, key, data)
                VALUES (:ns, :key, CAST(:data AS jsonb))
                ON CONFLICT (namespace, key) DO UPDATE
                SET data = EXCLUDED.data, updated_at = now()
                """
            ),
            {"ns": namespace, "key": key, "data": json.dumps(data)},
        )

    def list(self, namespace: str) -> list[Any]:
        rows = self.conn.execute(
            text("SELECT data FROM kv_store WHERE namespace = :ns ORDER BY created_at"),
            {"ns": namespace},
        ).fetchall()
        return [row[0] for row in rows]


@contextmanager
def _locked_store(lock_key: str) -> Iterator[_FileKvStore | _SqlKvStore]:
    engine = _get_engine()
    if engine is None:
        with _lock:
            yield _FileKvStore()
        return
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": lock_key})
        yield _SqlKvStore(conn)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def current_period(now: datetime | None = None) -> str:
    now = now or _now()
    return now.strftime("%Y-%m")


def reset_at_for_period(period: str) -> str:
    year_s, month_s = period.split("-", 1)
    year = int(year_s)
    month = int(month_s)
    if month == 12:
        reset = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        reset = datetime(year, month + 1, 1, tzinfo=UTC)
    return _iso(reset)


def normalize_plan(plan: str | None) -> str:
    value = str(plan or "free").strip().lower()
    if value == "basic":
        return "starter"
    return value if value in PLAN_LIMITS else "free"


def _limits_from_billing(billing: dict[str, Any]) -> dict[str, int | None]:
    plan = normalize_plan(str(billing.get("plan") or "free"))
    limits = dict(PLAN_LIMITS[plan])
    overrides = billing.get("entitlement_overrides") or billing.get("limits") or {}
    if isinstance(overrides, dict):
        aliases = {
            "seats": "seats",
            "seat_limit": "seats",
            "installer_slots": "installer_slots",
            "installer_limit": "installer_slots",
            "compile_credits": "compile_credits",
            "monthly_compile_credits": "compile_credits",
            "human_edit_tokens": "human_edit_tokens",
            "monthly_human_edit_tokens": "human_edit_tokens",
        }
        for raw_key, target_key in aliases.items():
            if raw_key not in overrides:
                continue
            raw_value = overrides.get(raw_key)
            if raw_value is None or str(raw_value).lower() == "unlimited":
                limits[target_key] = None
                continue
            try:
                limits[target_key] = max(0, int(raw_value))
            except (TypeError, ValueError):
                continue
    return limits


def usage_key(workspace_id: str, period: str) -> str:
    return f"{workspace_id}:{period}"


def _usage_defaults(workspace_id: str, period: str) -> dict[str, Any]:
    now = _iso(_now())
    return {
        "workspace_id": workspace_id,
        "period": period,
        "compile_credits_used": 0,
        "compile_input_tokens": 0,
        "compile_output_tokens": 0,
        "compile_requests": 0,
        "human_edit_input_tokens": 0,
        "human_edit_output_tokens": 0,
        "human_edit_requests": 0,
        "created_at": now,
        "updated_at": now,
    }


def _get_usage(store: _FileKvStore | _SqlKvStore, workspace_id: str, period: str) -> dict[str, Any]:
    data = store.get(USAGE_NS, usage_key(workspace_id, period))
    usage = _usage_defaults(workspace_id, period)
    if isinstance(data, dict):
        usage.update(data)
    return usage


def _set_usage(store: _FileKvStore | _SqlKvStore, usage: dict[str, Any]) -> None:
    usage["updated_at"] = _iso(_now())
    store.set(USAGE_NS, usage_key(str(usage["workspace_id"]), str(usage["period"])), usage)


def _reservation_defaults(
    *,
    reservation_id: str,
    workspace_id: str,
    period: str,
    plugin_id: str,
    workflow_id: str,
    session_id: str,
) -> dict[str, Any]:
    now_ts = time.time()
    now_iso = _iso(_now())
    return {
        "reservation_id": reservation_id,
        "workspace_id": workspace_id,
        "period": period,
        "amount": 1,
        "status": "reserved",
        "plugin_id": plugin_id,
        "workflow_id": workflow_id,
        "session_id": session_id,
        "idempotency_key": reservation_id,
        "created_at": now_iso,
        "updated_at": now_iso,
        "expires_at": now_ts + max(60, int(settings.entitlements_reservation_ttl_secs)),
    }


def _set_reservation(store: _FileKvStore | _SqlKvStore, row: dict[str, Any]) -> None:
    row["updated_at"] = _iso(_now())
    store.set(RESERVATION_NS, str(row["reservation_id"]), row)


def _reservation_matches(row: dict[str, Any], workspace_id: str, period: str) -> bool:
    return row.get("workspace_id") == workspace_id and row.get("period") == period


def _expire_reservations(store: _FileKvStore | _SqlKvStore, workspace_id: str, period: str) -> None:
    now_ts = time.time()
    for row in store.list(RESERVATION_NS):
        if not isinstance(row, dict) or not _reservation_matches(row, workspace_id, period):
            continue
        if row.get("status") != "reserved":
            continue
        try:
            expires_at = float(row.get("expires_at") or 0)
        except (TypeError, ValueError):
            expires_at = 0
        if expires_at <= now_ts:
            row["status"] = "expired"
            _set_reservation(store, row)


def _active_reserved_amount(store: _FileKvStore | _SqlKvStore, workspace_id: str, period: str) -> int:
    now_ts = time.time()
    total = 0
    for row in store.list(RESERVATION_NS):
        if not isinstance(row, dict) or not _reservation_matches(row, workspace_id, period):
            continue
        if row.get("status") != "reserved":
            continue
        try:
            expires_at = float(row.get("expires_at") or 0)
        except (TypeError, ValueError):
            expires_at = 0
        if expires_at > now_ts:
            total += int(row.get("amount") or 0)
    return total


def _installer_meta_paths() -> list[Path]:
    installers_dir = settings.data_dir / "installers"
    if not installers_dir.is_dir():
        return []
    return list(installers_dir.glob("*/meta.json"))


def installer_slot_count(workspace_id: str) -> int:
    slugs: set[str] = set()
    for plugin in list_plugins(workspace_id=workspace_id):
        if plugin.installer:
            slugs.add(plugin.slug)
    for meta_path in _installer_meta_paths():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("workspace_id") == workspace_id and meta.get("slug"):
            slugs.add(str(meta["slug"]))
    return len(slugs)


def installer_slug_has_release(workspace_id: str, slug: str) -> bool:
    for plugin in list_plugins(workspace_id=workspace_id):
        if plugin.slug == slug and plugin.installer:
            return True
    meta_path = settings.data_dir / "installers" / slug / "meta.json"
    if not meta_path.is_file():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return meta.get("workspace_id") == workspace_id


def _meter(used: int, limit: int | None, *, reserved: int = 0) -> dict[str, Any]:
    if limit is None:
        return {"used": used, "limit": None, "remaining": None, "unlimited": True}
    remaining = max(0, int(limit) - int(used) - int(reserved))
    return {"used": used, "limit": int(limit), "remaining": remaining, "unlimited": False}


def _clerk_org_member_count(principal: Principal) -> int | None:
    if principal.auth_provider != "clerk" or not principal.workspace_id.startswith("org_"):
        return None
    secret = str(settings.clerk_secret_key or "").strip()
    if not secret:
        return None
    req = urllib.request.Request(
        f"https://api.clerk.com/v1/organizations/{quote(principal.workspace_id, safe='')}/memberships?limit=1"
    )
    req.add_header("Authorization", f"Bearer {secret}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        try:
            return max(1, int(payload.get("total_count")))
        except (TypeError, ValueError):
            data = payload.get("data")
            if isinstance(data, list):
                return max(1, len(data))
    return None


def current_entitlements(principal: Principal) -> dict[str, Any]:
    billing = billing_for(principal)
    plan = normalize_plan(str(billing.get("plan") or "free"))
    limits = _limits_from_billing(billing)
    period = current_period()
    workspace_id = principal.workspace_id
    with _locked_store(f"entitlements:{workspace_id}:{period}") as store:
        _expire_reservations(store, workspace_id, period)
        usage = _get_usage(store, workspace_id, period)
        reserved_compile = _active_reserved_amount(store, workspace_id, period)
    human_edit_used = int(usage.get("human_edit_input_tokens") or 0) + int(
        usage.get("human_edit_output_tokens") or 0
    )
    return {
        "workspace_id": workspace_id,
        "plan": plan,
        "period": period,
        "reset_at": reset_at_for_period(period),
        "meters": {
            "seats": _meter(
                _clerk_org_member_count(principal) or membership_count_for(workspace_id),
                limits["seats"],
            ),
            "installer_slots": _meter(installer_slot_count(workspace_id), limits["installer_slots"]),
            "compile_credits": _meter(
                int(usage.get("compile_credits_used") or 0),
                limits["compile_credits"],
                reserved=reserved_compile,
            ),
            "human_edit_tokens": _meter(human_edit_used, limits["human_edit_tokens"]),
        },
    }


def reserve_compile_credit(
    principal: Principal,
    *,
    reservation_id: str,
    plugin_id: str = "",
    workflow_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    if not reservation_id.strip():
        raise EntitlementError("invalid_reservation_id", 400)
    billing = billing_for(principal)
    limits = _limits_from_billing(billing)
    period = current_period()
    workspace_id = principal.workspace_id
    with _locked_store(f"compile-reserve:{workspace_id}:{period}") as store:
        _expire_reservations(store, workspace_id, period)
        usage = _get_usage(store, workspace_id, period)
        existing = store.get(RESERVATION_NS, reservation_id)
        if isinstance(existing, dict):
            if existing.get("workspace_id") != workspace_id:
                raise EntitlementError("compile_reservation_conflict", 409)
            reserved_amount = _active_reserved_amount(store, workspace_id, period)
            remaining = _remaining_compile(limits["compile_credits"], usage, reserved_amount)
            return {
                "reservation_id": reservation_id,
                "status": str(existing.get("status") or "reserved"),
                "remaining_compile_credits": remaining,
            }
        reserved_amount = _active_reserved_amount(store, workspace_id, period)
        limit = limits["compile_credits"]
        if (
            settings.entitlements_enforce_compile
            and limit is not None
            and int(usage.get("compile_credits_used") or 0) + reserved_amount + 1 > int(limit)
        ):
            raise EntitlementError("compile_credit_limit_exceeded", 402)
        row = _reservation_defaults(
            reservation_id=reservation_id,
            workspace_id=workspace_id,
            period=period,
            plugin_id=plugin_id,
            workflow_id=workflow_id,
            session_id=session_id,
        )
        _set_reservation(store, row)
        remaining = _remaining_compile(limit, usage, reserved_amount + 1)
    return {
        "reservation_id": reservation_id,
        "status": "reserved",
        "remaining_compile_credits": remaining,
    }


def _remaining_compile(
    limit: int | None,
    usage: dict[str, Any],
    reserved_amount: int,
) -> int | None:
    if limit is None:
        return None
    return max(0, int(limit) - int(usage.get("compile_credits_used") or 0) - reserved_amount)


def commit_compile_credit(principal: Principal, reservation_id: str) -> dict[str, Any]:
    period = current_period()
    workspace_id = principal.workspace_id
    billing = billing_for(principal)
    limits = _limits_from_billing(billing)
    with _locked_store(f"compile-commit:{workspace_id}:{period}") as store:
        _expire_reservations(store, workspace_id, period)
        usage = _get_usage(store, workspace_id, period)
        row = store.get(RESERVATION_NS, reservation_id)
        if not isinstance(row, dict) or row.get("workspace_id") != workspace_id:
            raise EntitlementError("compile_reservation_not_found", 404)
        status = str(row.get("status") or "")
        if status == "committed":
            return {"reservation_id": reservation_id, "status": "committed"}
        if status != "reserved":
            raise EntitlementError("compile_reservation_not_reserved", 409)
        usage["compile_credits_used"] = int(usage.get("compile_credits_used") or 0) + int(
            row.get("amount") or 0
        )
        _set_usage(store, usage)
        row["status"] = "committed"
        _set_reservation(store, row)
        remaining = _remaining_compile(
            limits["compile_credits"],
            usage,
            _active_reserved_amount(store, workspace_id, period),
        )
    return {"reservation_id": reservation_id, "status": "committed", "remaining_compile_credits": remaining}


def release_compile_credit(principal: Principal, reservation_id: str) -> dict[str, Any]:
    period = current_period()
    workspace_id = principal.workspace_id
    with _locked_store(f"compile-release:{workspace_id}:{period}") as store:
        row = store.get(RESERVATION_NS, reservation_id)
        if not isinstance(row, dict) or row.get("workspace_id") != workspace_id:
            raise EntitlementError("compile_reservation_not_found", 404)
        status = str(row.get("status") or "")
        if status == "reserved":
            row["status"] = "released"
            _set_reservation(store, row)
            status = "released"
    return {"reservation_id": reservation_id, "status": status}


def record_llm_usage(
    principal: Principal,
    *,
    usage_class: str,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, Any]:
    usage_class = str(usage_class or "compile").strip()
    if usage_class not in ALLOWED_USAGE_CLASSES:
        raise EntitlementError("invalid_usage_class", 400)
    billing = billing_for(principal)
    limits = _limits_from_billing(billing)
    period = current_period()
    workspace_id = principal.workspace_id
    with _locked_store(f"llm-usage:{workspace_id}:{period}") as store:
        usage = _get_usage(store, workspace_id, period)
        if usage_class == "human_edit":
            used = int(usage.get("human_edit_input_tokens") or 0) + int(
                usage.get("human_edit_output_tokens") or 0
            )
            limit = limits["human_edit_tokens"]
            if settings.entitlements_enforce_human_edit and limit is not None and used >= int(limit):
                raise EntitlementError("human_edit_pool_exceeded", 402)
            usage["human_edit_input_tokens"] = int(usage.get("human_edit_input_tokens") or 0) + max(
                0, int(input_tokens)
            )
            usage["human_edit_output_tokens"] = int(usage.get("human_edit_output_tokens") or 0) + max(
                0, int(output_tokens)
            )
            usage["human_edit_requests"] = int(usage.get("human_edit_requests") or 0) + 1
        else:
            usage["compile_input_tokens"] = int(usage.get("compile_input_tokens") or 0) + max(
                0, int(input_tokens)
            )
            usage["compile_output_tokens"] = int(usage.get("compile_output_tokens") or 0) + max(
                0, int(output_tokens)
            )
            usage["compile_requests"] = int(usage.get("compile_requests") or 0) + 1
        _set_usage(store, usage)
    return usage


def ensure_human_edit_available(principal: Principal, *, estimated_tokens: int = 0) -> None:
    billing = billing_for(principal)
    limits = _limits_from_billing(billing)
    limit = limits["human_edit_tokens"]
    if limit is None:
        return
    period = current_period()
    workspace_id = principal.workspace_id
    with _locked_store(f"human-edit-check:{workspace_id}:{period}") as store:
        usage = _get_usage(store, workspace_id, period)
    used = int(usage.get("human_edit_input_tokens") or 0) + int(usage.get("human_edit_output_tokens") or 0)
    if settings.entitlements_enforce_human_edit and used >= int(limit):
        raise EntitlementError("human_edit_pool_exceeded", 402)


def ensure_installer_slot_available(principal: Principal, slug: str) -> dict[str, Any]:
    billing = billing_for(principal)
    limits = _limits_from_billing(billing)
    limit = limits["installer_slots"]
    workspace_id = principal.workspace_id
    existing_slot = installer_slug_has_release(workspace_id, slug)
    used = installer_slot_count(workspace_id)
    if (
        settings.entitlements_enforce_installers
        and not existing_slot
        and limit is not None
        and used >= int(limit)
    ):
        raise EntitlementError("installer_limit_exceeded", 402)
    return {
        "slug": slug,
        "existing_slot": existing_slot,
        "used": used,
        "limit": limit,
        "remaining": None if limit is None else max(0, int(limit) - used),
    }
