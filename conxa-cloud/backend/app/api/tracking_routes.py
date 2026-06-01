"""Lightweight telemetry ingestion and query routes for company-scoped tracking.

POST /api/tracking/{company}/events     — called by runtime, HMAC-authenticated
POST /api/v1/tracking/{company}/events  — same ingest endpoint for v1 API bases
GET  /api/v1/tracking/{company}/runs    — paginated run summaries (Clerk-authenticated)
GET  /api/v1/tracking/{company}/runs/{run_id} — single run event timeline
"""

from __future__ import annotations

import time
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from conxa_core.db import db_append, db_get, db_list_kv
from conxa_core.config import settings
from conxa_core.storage.plugin_store import list_plugins
from app.services.saas import (
    Principal,
    ensure_principal,
    personal_workspace_id,
    principal_from_request,
    visible_workspace_ids_for,
)

router = APIRouter(prefix="/tracking", tags=["tracking"])
public_router = APIRouter(prefix="/api/tracking", tags=["tracking"])


def current_principal(request: Request) -> Principal:
    principal = principal_from_request(request)
    ensure_principal(principal)
    return principal


def _verify_token(company: str, token: str) -> dict[str, Any] | None:
    """Verify the tracking token for a company.

    Published packs get a server-issued token stored in kv_store. Local dev
    without a stored token or secret still accepts telemetry for convenience.
    """
    stored = db_get("tracking_tokens", company)
    if isinstance(stored, dict) and stored.get("token"):
        expected = str(stored.get("token") or "")
        if token and secrets.compare_digest(expected, token):
            return stored
        return None
    if not settings.tracking_hmac_secret:
        return {"workspace_id": ""}
    return None


def _owner_from_record(record: dict[str, Any]) -> str:
    owner = str(record.get("owner_user_id") or "")
    if owner:
        return owner
    workspace_id = str(record.get("workspace_id") or "")
    if workspace_id.startswith("personal_"):
        return workspace_id.removeprefix("personal_")
    return ""


def _record_visible_to_principal(record: dict[str, Any], principal: Principal) -> bool:
    workspace_id = str(record.get("workspace_id") or "")
    if not workspace_id or workspace_id == principal.workspace_id:
        return True
    if workspace_id == personal_workspace_id(principal.user_id):
        owner = _owner_from_record(record)
        return not owner or owner == principal.user_id
    return False


def _batches_for_workspace(value: Any, workspace_id: str) -> list[dict]:
    batches: list[dict] = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    if not workspace_id:
        return batches
    return [
        batch
        for batch in batches
        if not batch.get("workspace_id") or batch.get("workspace_id") == workspace_id
    ]


def _batches_for_principal(value: Any, principal: Principal) -> list[dict]:
    batches: list[dict] = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    visible_ids = set(visible_workspace_ids_for(principal))
    return [
        batch
        for batch in batches
        if not batch.get("workspace_id") or batch.get("workspace_id") in visible_ids
    ]


def _run_summary(run_id: str, batches: list[dict]) -> dict:
    """Derive a compact summary from a list of ingested event batches."""
    events: list[dict] = []
    meta = batches[-1] if batches else {}
    for b in batches:
        events.extend(b.get("events", []))

    status = "running"
    duration_ms = 0
    total_steps = 0
    recovered_steps = 0
    failed_step_id = None
    failure_code = None
    started_at = 0

    for evt in events:
        code = evt.get("e", "")
        if code == "wf_start":
            started_at = evt.get("ts", 0)
        elif code == "wf_ok":
            status = "ok"
            duration_ms = evt.get("dur", 0)
            total_steps = evt.get("tot", 0)
            recovered_steps = evt.get("rec", 0)
        elif code == "wf_fail":
            status = "fail"
            duration_ms = evt.get("dur", 0)
            failed_step_id = evt.get("fsi")
            failure_code = evt.get("fc")

    return {
        "run_id":         meta.get("run_id", run_id),
        "plugin_id":      meta.get("plugin_id", ""),
        "plugin_ver":     meta.get("plugin_ver", ""),
        "runtime_ver":    meta.get("runtime_ver", ""),
        "uid":            meta.get("uid", ""),
        "wid":            meta.get("wid", ""),
        "status":         status,
        "duration_ms":    duration_ms,
        "total_steps":    total_steps,
        "recovered_steps": recovered_steps,
        "failed_step_id": failed_step_id,
        "failure_code":   failure_code,
        "started_at":     started_at,
        "server_ts":      meta.get("server_ts", 0),
    }


def _company_run_stats(company: str, principal: Principal) -> tuple[int, float]:
    run_count = 0
    last_seen = 0.0
    for _run_id, batches in db_list_kv(f"tracking/{company}"):
        scoped = _batches_for_principal(batches, principal)
        if not scoped:
            continue
        run_count += 1
        for batch in scoped:
            try:
                last_seen = max(last_seen, float(batch.get("server_ts") or 0))
            except (TypeError, ValueError):
                continue
    return run_count, last_seen


def _tracking_company_rows(principal: Principal) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    for key, record in db_list_kv("tracking_tokens"):
        if not isinstance(record, dict):
            continue
        if not _record_visible_to_principal(record, principal):
            continue
        workspace_id = str(record.get("workspace_id") or "")
        company = str(record.get("company") or key or "").strip()
        if not company:
            continue
        run_count, last_seen = _company_run_stats(company, principal)
        rows[company] = {
            "company": company,
            "workspace_id": workspace_id or principal.workspace_id,
            "run_count": run_count,
            "last_seen": last_seen or float(record.get("updated_at") or 0),
        }

    visible_workspace_ids = set(visible_workspace_ids_for(principal))
    for plugin in list_plugins():
        if plugin.workspace_id != principal.workspace_id and not (
            plugin.workspace_id in visible_workspace_ids and plugin.owner_user_id == principal.user_id
        ):
            continue
        company = str(plugin.slug or plugin.name or "").strip()
        if not company:
            continue
        current = rows.get(company)
        if current is None:
            run_count, last_seen = _company_run_stats(company, principal)
            rows[company] = {
                "company": company,
                "workspace_id": principal.workspace_id,
                "run_count": run_count,
                "last_seen": last_seen or float(plugin.updated_at or 0),
            }
        elif not current.get("last_seen"):
            current["last_seen"] = float(plugin.updated_at or 0)

    return sorted(
        rows.values(),
        key=lambda row: (float(row.get("last_seen") or 0), str(row.get("company") or "")),
        reverse=True,
    )


def _tracking_diagnostics(principal: Principal) -> dict[str, Any]:
    visible_workspace_ids = set(visible_workspace_ids_for(principal))
    visible_companies = _tracking_company_rows(principal)
    same_user_personal = 0
    hidden_same_user_personal = 0
    for _key, record in db_list_kv("tracking_tokens"):
        if not isinstance(record, dict):
            continue
        workspace_id = str(record.get("workspace_id") or "")
        owner = _owner_from_record(record)
        if workspace_id == personal_workspace_id(principal.user_id) and (not owner or owner == principal.user_id):
            same_user_personal += 1
            if workspace_id not in visible_workspace_ids:
                hidden_same_user_personal += 1
    plugin_count = 0
    for plugin in list_plugins():
        if plugin.workspace_id == principal.workspace_id or (
            plugin.workspace_id in visible_workspace_ids and plugin.owner_user_id == principal.user_id
        ):
            plugin_count += 1
    return {
        "workspace_id": principal.workspace_id,
        "user_id": principal.user_id,
        "personal_workspace_id": personal_workspace_id(principal.user_id),
        "identity_source": principal.identity_source,
        "proxy_identity_trusted": principal.proxy_identity_trusted,
        "visible_workspace_ids": list(visible_workspace_ids),
        "visible_company_count": len(visible_companies),
        "plugin_count": plugin_count,
        "same_user_personal_company_count": same_user_personal,
        "hidden_same_user_personal_count": hidden_same_user_personal,
    }


@public_router.post("/{company}/events", status_code=202)
@router.post("/{company}/events", status_code=202)
async def ingest_events(company: str, request: Request) -> dict[str, Any]:
    """Accept a compact event batch from the runtime. Fast 202 — never blocks execution."""
    token = request.headers.get("x-tracking-token", "")
    token_record = _verify_token(company, token)
    if token_record is None:
        raise HTTPException(status_code=401, detail="invalid_tracking_token")

    body = await request.json()

    run_id = body.get("rid", "")
    if not run_id:
        return {"ok": True}  # drop malformed batches silently

    enriched: dict[str, Any] = {
        "run_id":      run_id,
        "company":     company,
        "plugin_id":   body.get("pid", ""),
        "plugin_ver":  body.get("pv", ""),
        "runtime_ver": body.get("rv", ""),
        "uid":         body.get("uid", ""),
        "wid":         body.get("wid", ""),
        "workspace_id": token_record.get("workspace_id", ""),
        "owner_user_id": token_record.get("owner_user_id", ""),
        "server_ts":   time.time(),
        "events":      body.get("evts", []),
        "schema_v":    body.get("sv", 1),
    }
    db_append(f"tracking/{company}", run_id, [enriched])
    return {"ok": True}


@router.get("/companies")
def list_tracking_companies(
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    """Return companies with workspace-visible tracking or plugin metadata."""
    companies = _tracking_company_rows(principal)
    return {
        "companies": companies,
        "total": len(companies),
        "workspace_id": principal.workspace_id,
    }


@router.get("/diagnostics")
def tracking_diagnostics(
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    """Return safe workspace-scoping diagnostics for dashboard visibility."""
    return _tracking_diagnostics(principal)


@router.get("/{company}/runs")
def list_runs(
    company: str,
    limit: int = 50,
    offset: int = 0,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    """Return paginated run summaries for a company."""
    pairs = db_list_kv(f"tracking/{company}")
    summaries = []
    hidden_workspace_runs = 0
    for run_id, batches in pairs:
        scoped = _batches_for_principal(batches, principal)
        if scoped:
            summaries.append(_run_summary(run_id, scoped))
        else:
            hidden_workspace_runs += 1

    # newest first by server_ts
    summaries.sort(key=lambda s: s.get("server_ts", 0), reverse=True)
    return {
        "runs": summaries[offset : offset + limit],
        "total": len(summaries),
        "workspace_id": principal.workspace_id,
        "total_all_workspaces": len(pairs),
        "hidden_workspace_runs": hidden_workspace_runs,
    }


@router.get("/{company}/runs/{run_id}")
def get_run_timeline(
    company: str,
    run_id: str,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    """Return the flattened event timeline for a single run."""
    data = db_get(f"tracking/{company}", run_id)
    if not data:
        raise HTTPException(status_code=404, detail="run_not_found")

    batches = _batches_for_principal(data, principal)
    if not batches:
        raise HTTPException(status_code=404, detail="run_not_found_for_workspace")
    events: list[dict] = []
    for b in batches:
        events.extend(b.get("events", []))
    events.sort(key=lambda e: e.get("ts", 0))

    meta = batches[-1] if batches else {}
    return {
        "run_id":      run_id,
        "company":     company,
        "plugin_id":   meta.get("plugin_id", ""),
        "plugin_ver":  meta.get("plugin_ver", ""),
        "runtime_ver": meta.get("runtime_ver", ""),
        "uid":         meta.get("uid", ""),
        "wid":         meta.get("wid", ""),
        "workspace_id": meta.get("workspace_id", ""),
        "timeline":    events,
    }
