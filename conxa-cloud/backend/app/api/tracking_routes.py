"""Lightweight telemetry ingestion and query routes for company-scoped tracking.

POST /api/tracking/{company}/events     — called by runtime, HMAC-authenticated
POST /api/v1/tracking/{company}/events  — same ingest endpoint for v1 API bases
GET  /api/v1/tracking/{company}/runs    — paginated run summaries (Clerk-authenticated)
GET  /api/v1/tracking/{company}/runs/{run_id} — single run event timeline
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from conxa_core.db import db_append, db_get, db_list, db_list_kv
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

_DAY_MS = 86_400_000
_RECOVERY_TYPES = ("Selector", "Text Anchor", "Text Variant", "Vision")
_RECOVERY_TIERS = (
    ("Tier 1", "Selector"),
    ("Tier 2", "Text Anchor"),
    ("Tier 3", "Text Variant"),
    ("Tier 4", "Vision"),
)


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
        "proxy_identity_status": principal.proxy_identity_status,
        "visible_workspace_ids": list(visible_workspace_ids),
        "visible_company_count": len(visible_companies),
        "plugin_count": plugin_count,
        "same_user_personal_company_count": same_user_personal,
        "hidden_same_user_personal_count": hidden_same_user_personal,
    }


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _epoch_ms(value: Any) -> int:
    n = _number(value)
    if n <= 0:
        return 0
    return int(n if n > 10_000_000_000 else n * 1000)


def _date_key(epoch_ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(epoch_ms / 1000))


def _range_days(value: str) -> int:
    return 30 if str(value or "").lower() == "30d" else 7


def _visible_runtime_registrations(principal: Principal) -> list[dict[str, Any]]:
    visible_ids = set(visible_workspace_ids_for(principal))
    registrations: list[dict[str, Any]] = []
    for reg in db_list("runtime_registrations"):
        if not isinstance(reg, dict):
            continue
        workspace_id = str(reg.get("workspace_id") or "")
        if not workspace_id or workspace_id not in visible_ids:
            continue
        registrations.append(reg)
    return registrations


def _visible_run_records(principal: Principal) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in _tracking_company_rows(principal):
        company = str(row.get("company") or "").strip()
        if not company:
            continue
        for run_id, batches in db_list_kv(f"tracking/{company}"):
            scoped = _batches_for_principal(batches, principal)
            if not scoped:
                continue
            events: list[dict[str, Any]] = []
            for batch in scoped:
                events.extend(batch.get("events", []))
            summary = _run_summary(run_id, scoped)
            records.append({"company": company, "summary": summary, "events": events})
    records.sort(key=lambda r: _record_time_ms(r), reverse=True)
    return records


def _record_time_ms(record: dict[str, Any]) -> int:
    summary = record.get("summary") or {}
    return max(_epoch_ms(summary.get("started_at")), _epoch_ms(summary.get("server_ts")))


def _event_recovery_type(evt: dict[str, Any]) -> str:
    code = str(evt.get("e") or "").lower()
    key = str(evt.get("rt") or evt.get("sc") or evt.get("tier") or evt.get("sel") or "").lower()
    if code not in {"rec_ok", "tier_ok"}:
        return ""
    if code == "tier_ok" and key == "tier1_compiled" and not evt.get("sel"):
        return ""
    if key in {"selector", "selector_retry", "candidate_fallback", "dialog_scope", "tier1_compiled"}:
        return "Selector"
    if key.startswith("a11y") or key in {"text_anchor", "tier2_a11y"}:
        return "Text Anchor"
    if key in {"text_variant", "fuzzy", "fuzzy_dom"}:
        return "Text Variant"
    if key in {"vision", "vision_recovery", "tier4_vision", "llm_intent", "tier3_llm"}:
        return "Vision"
    return ""


def _event_recovery_tier(evt: dict[str, Any], recovery_type: str) -> str:
    key = str(evt.get("rt") or evt.get("sc") or evt.get("tier") or evt.get("sel") or "").lower()
    if key in {"selector", "selector_retry", "candidate_fallback", "dialog_scope", "tier1_compiled"}:
        return "Tier 1"
    if key.startswith("a11y") or key in {"text_anchor", "tier2_a11y"}:
        return "Tier 2"
    if key in {"text_variant", "fuzzy", "fuzzy_dom", "tier3_llm", "llm_intent"}:
        return "Tier 3"
    if key in {"vision", "vision_recovery", "tier4_vision"}:
        return "Tier 4"
    for tier, mapped_type in _RECOVERY_TIERS:
        if recovery_type == mapped_type:
            return tier
    return "Unknown"


def _run_has_recovery(record: dict[str, Any]) -> bool:
    summary = record.get("summary") or {}
    if int(_number(summary.get("recovered_steps"))) > 0:
        return True
    return any(_event_recovery_type(evt) for evt in record.get("events") or [])


def _failed_step_index(record: dict[str, Any]) -> int | None:
    summary = record.get("summary") or {}
    value = summary.get("failed_step_id")
    if value is None:
        for evt in reversed(record.get("events") or []):
            if evt.get("e") == "step_fail" and evt.get("si") is not None:
                value = evt.get("si")
                break
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _event_step_index(evt: dict[str, Any]) -> int | None:
    value = evt.get("si")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _dashboard_metrics(principal: Principal, range_value: str) -> dict[str, Any]:
    days = _range_days(range_value)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (days * _DAY_MS)
    last_24h_ms = now_ms - _DAY_MS

    registrations = _visible_runtime_registrations(principal)
    install_keys = {
        str(reg.get("install_id") or f"{reg.get('company', '')}:{reg.get('platform', '')}")
        for reg in registrations
        if reg.get("install_id") or reg.get("company") or reg.get("platform")
    }
    active_install_keys = {
        str(reg.get("install_id") or f"{reg.get('company', '')}:{reg.get('platform', '')}")
        for reg in registrations
        if _epoch_ms(reg.get("last_seen")) >= start_ms
        and (reg.get("install_id") or reg.get("company") or reg.get("platform"))
    }

    all_records = _visible_run_records(principal)
    range_records = [record for record in all_records if _record_time_ms(record) >= start_ms]
    last_24h_records = [record for record in all_records if _record_time_ms(record) >= last_24h_ms]
    completed_records = [r for r in range_records if (r.get("summary") or {}).get("status") in {"ok", "fail"}]
    ok_records = [r for r in completed_records if (r.get("summary") or {}).get("status") == "ok"]
    failed_records = [r for r in completed_records if (r.get("summary") or {}).get("status") == "fail"]
    recovered_records = [r for r in range_records if _run_has_recovery(r)]
    durations = [
        int(_number((r.get("summary") or {}).get("duration_ms")))
        for r in completed_records
        if _number((r.get("summary") or {}).get("duration_ms")) > 0
    ]

    range_install_ids = {
        str((r.get("summary") or {}).get("uid") or "")
        for r in range_records
        if (r.get("summary") or {}).get("uid")
    }
    active_users = len(active_install_keys | range_install_ids)
    active_companies = len({str(r.get("company") or "") for r in range_records if r.get("company")})

    recovery_counts = {name: 0 for name in _RECOVERY_TYPES}
    recovery_step_usage: dict[str, dict[str, Any]] = {}
    recovery_workflows: dict[str, dict[str, Any]] = {}

    def record_recovery_usage(
        *,
        company: str,
        workflow: str,
        step_index: int | None,
        recovery_type: str,
        tier: str,
        count: int,
        last_seen: int,
    ) -> None:
        if count <= 0:
            return
        step_label = f"Step {step_index + 1}" if step_index is not None else "Unknown step"
        flat_key = f"{company}:{workflow}:{step_index if step_index is not None else 'unknown'}:{recovery_type}"
        current = recovery_step_usage.setdefault(
            flat_key,
            {
                "company": company,
                "workflow": workflow,
                "step_index": step_index,
                "step_label": step_label,
                "recovery_type": recovery_type,
                "tier": tier,
                "count": 0,
                "last_seen": 0,
            },
        )
        current["count"] += count
        current["last_seen"] = max(int(current["last_seen"]), last_seen)

        workflow_key = f"{company}:{workflow}"
        workflow_row = recovery_workflows.setdefault(
            workflow_key,
            {
                "company": company,
                "workflow": workflow,
                "count": 0,
                "last_seen": 0,
                "steps": {},
            },
        )
        workflow_row["count"] += count
        workflow_row["last_seen"] = max(int(workflow_row["last_seen"]), last_seen)

        steps = workflow_row["steps"]
        step_key = str(step_index) if step_index is not None else "unknown"
        step_row = steps.setdefault(
            step_key,
            {
                "step_index": step_index,
                "step_label": step_label,
                "total_count": 0,
                "last_seen": 0,
                "tier_counts": {
                    name: {"tier": name, "recovery_type": mapped_type, "count": 0}
                    for name, mapped_type in _RECOVERY_TIERS
                },
            },
        )
        step_row["total_count"] += count
        step_row["last_seen"] = max(int(step_row["last_seen"]), last_seen)
        if tier not in step_row["tier_counts"]:
            step_row["tier_counts"][tier] = {"tier": tier, "recovery_type": recovery_type, "count": 0}
        step_row["tier_counts"][tier]["count"] += count

    for record in range_records:
        summary = record.get("summary") or {}
        company = str(record.get("company") or "")
        workflow = str(summary.get("plugin_id") or "Unknown workflow")
        for evt in record.get("events") or []:
            recovery_type = _event_recovery_type(evt)
            if recovery_type:
                recovery_counts[recovery_type] += 1
                step_index = _event_step_index(evt)
                record_recovery_usage(
                    company=company,
                    workflow=workflow,
                    step_index=step_index,
                    recovery_type=recovery_type,
                    tier=_event_recovery_tier(evt, recovery_type),
                    count=1,
                    last_seen=_epoch_ms(evt.get("ts")) or _record_time_ms(record),
                )
    # Older runtimes may only send wf_ok.rec. Keep recovered runs visible as selector saves.
    if not any(recovery_counts.values()):
        recovery_counts["Selector"] = sum(
            1 for record in range_records if int(_number((record.get("summary") or {}).get("recovered_steps"))) > 0
        )
        for record in range_records:
            recovered_steps = int(_number((record.get("summary") or {}).get("recovered_steps")))
            if recovered_steps <= 0:
                continue
            summary = record.get("summary") or {}
            company = str(record.get("company") or "")
            workflow = str(summary.get("plugin_id") or "Unknown workflow")
            record_recovery_usage(
                company=company,
                workflow=workflow,
                step_index=None,
                recovery_type="Selector",
                tier="Tier 1",
                count=recovered_steps,
                last_seen=_record_time_ms(record),
            )

    workflow_failures: dict[str, dict[str, Any]] = {}
    step_failures: dict[str, dict[str, Any]] = {}
    for record in failed_records:
        summary = record.get("summary") or {}
        workflow = str(summary.get("plugin_id") or "Unknown workflow")
        current = workflow_failures.setdefault(
            workflow,
            {"workflow": workflow, "failed_executions": 0, "last_failure_code": "", "last_seen": 0},
        )
        current["failed_executions"] += 1
        current["last_failure_code"] = summary.get("failure_code") or current["last_failure_code"]
        current["last_seen"] = max(int(current["last_seen"]), _record_time_ms(record))

        step_index = _failed_step_index(record)
        step_key = f"{workflow}:{step_index if step_index is not None else 'unknown'}"
        step = step_failures.setdefault(
            step_key,
            {
                "workflow": workflow,
                "step_index": step_index,
                "step_label": f"Step {step_index + 1}" if step_index is not None else "Unknown step",
                "failed_executions": 0,
                "last_failure_code": "",
                "last_seen": 0,
            },
        )
        step["failed_executions"] += 1
        step["last_failure_code"] = summary.get("failure_code") or step["last_failure_code"]
        step["last_seen"] = max(int(step["last_seen"]), _record_time_ms(record))

    buckets = {
        _date_key(now_ms - ((_range_days(range_value) - 1 - i) * _DAY_MS)): {
            "date": _date_key(now_ms - ((_range_days(range_value) - 1 - i) * _DAY_MS)),
            "executions": 0,
            "successful": 0,
            "failed": 0,
            "recovered": 0,
        }
        for i in range(days)
    }
    for record in range_records:
        key = _date_key(_record_time_ms(record))
        if key not in buckets:
            continue
        summary = record.get("summary") or {}
        buckets[key]["executions"] += 1
        if summary.get("status") == "ok":
            buckets[key]["successful"] += 1
        if summary.get("status") == "fail":
            buckets[key]["failed"] += 1
        if _run_has_recovery(record):
            buckets[key]["recovered"] += 1

    total_range = len(range_records)
    success_rate = round((len(ok_records) / len(completed_records)) * 100, 1) if completed_records else 0.0
    recovery_rate = round((len(recovered_records) / total_range) * 100, 1) if total_range else 0.0

    return {
        "range": f"{days}d",
        "metrics": {
            "total_installs": len(install_keys),
            "active_users": active_users,
            "active_companies": active_companies,
            "total_executions": len(all_records),
            "executions_last_24h": len(last_24h_records),
            "success_rate": success_rate,
            "failed_executions": len(failed_records),
            "recovery_rate": recovery_rate,
            "average_execution_time": round(sum(durations) / len(durations)) if durations else 0,
        },
        "recovery_type_usage": [
            {"type": name, "count": recovery_counts[name]}
            for name in _RECOVERY_TYPES
        ],
        "recovery_usage_by_step": sorted(
            recovery_step_usage.values(),
            key=lambda row: (row["count"], row["last_seen"]),
            reverse=True,
        )[:12],
        "recovery_usage_by_workflow": [
            {
                "company": row["company"],
                "workflow": row["workflow"],
                "count": row["count"],
                "last_seen": row["last_seen"],
                "steps": [
                    {
                        "step_index": step["step_index"],
                        "step_label": step["step_label"],
                        "total_count": step["total_count"],
                        "last_seen": step["last_seen"],
                        "tier_counts": [
                            step["tier_counts"][tier]
                            for tier, _mapped_type in _RECOVERY_TIERS
                            if step["tier_counts"][tier]["count"] > 0
                        ],
                    }
                    for step in sorted(
                        row["steps"].values(),
                        key=lambda step: (step["total_count"], step["last_seen"]),
                        reverse=True,
                    )
                ],
            }
            for row in sorted(
                recovery_workflows.values(),
                key=lambda row: (row["count"], row["last_seen"]),
                reverse=True,
            )[:8]
        ],
        "most_failed_workflows": sorted(
            workflow_failures.values(),
            key=lambda row: (row["failed_executions"], row["last_seen"]),
            reverse=True,
        )[:6],
        "most_failed_steps": sorted(
            step_failures.values(),
            key=lambda row: (row["failed_executions"], row["last_seen"]),
            reverse=True,
        )[:6],
        "execution_trend": list(buckets.values()),
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


@router.get("/dashboard")
def tracking_dashboard(
    range: str = "7d",
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    """Return workspace-scoped adoption, reliability, and recovery aggregates."""
    return _dashboard_metrics(principal, range)


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
