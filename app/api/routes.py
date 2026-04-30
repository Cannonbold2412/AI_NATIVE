"""HTTP surface — recorder, compile pipeline, skill retrieval, 1-click fix, metrics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from app.compiler.build import compile_skill_package
from app.compiler.patch import apply_step_patch, revalidate_step
from app.compiler.wait_for_shape import leaf_wait_for_conditions, leaf_wait_type
from app.confidence.uncertainty import audit_reference
from app.llm.anchor_vision_llm import VisionAnchorGenerationError
from app.metrics.store import metrics
from app.pipeline.run import run_pipeline
from app.recorder.session import registry
from app.storage.json_store import read_skill, write_skill
from app.storage.session_events import read_session_events

router = APIRouter()
HARD_AUDIT_ISSUES = {
    "missing_selectors",
    "empty_primary_css",
    "anchors_empty",
    "anchors_empty_required",
    "weak_visual_bbox",
}
GENERIC_INTENTS = {"interact", "provide_input", "perform_action"}


class StartRecordBody(BaseModel):
    start_url: HttpUrl = Field(..., description="Initial navigation target for the headed recorder.")


class CompileBody(BaseModel):
    session_id: str
    skill_title: str = ""


class UpdateStepBody(BaseModel):
    skill_id: str
    step_index: int
    patch: dict[str, Any] = Field(default_factory=dict)
    assist_llm: bool = True


def _load_events_for_compile(session_id: str) -> list[dict[str, Any]]:
    sess = registry.get(session_id)
    mem_events = sess.snapshot_events() if sess else []
    disk_events = read_session_events(session_id)
    if mem_events:
        return mem_events
    return disk_events


def _build_audit_report(steps: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    audit_report: list[dict[str, Any]] = []
    for idx, step in enumerate(steps):
        issues = audit_reference(
            {
                "action_kind": step.action["action"] if isinstance(step.action, dict) else step.action,
                "target": step.signals.get("dom") or {},
                "selectors": step.signals.get("selectors") or {},
                "semantic": step.signals.get("semantic") or {},
                "context": step.signals.get("context") or {},
                "anchors": step.signals.get("anchors") or [],
                "visual": step.signals.get("visual") or {},
                "state_after": (step.signals.get("context") or {}).get("state_after") or "",
                "page_url": (step.signals.get("context") or {}).get("page_url") or "",
                "page_title": (step.signals.get("context") or {}).get("page_title") or "",
            }
        )
        if issues:
            audit_report.append({"step_index": idx, "issues": issues})
    hard_failures = [
        item for item in audit_report if any(issue in HARD_AUDIT_ISSUES for issue in item["issues"])
    ]
    return audit_report, hard_failures


def _build_preview_diff(raw: list[dict[str, Any]], normalized: list[dict[str, Any]], steps: list[dict[str, Any]]) -> dict[str, Any]:
    wait_types: dict[str, int] = {}
    generic_intent_count = 0
    for step in steps:
        wait_for = (step.get("validation") or {}).get("wait_for") or {}
        wf_d = dict(wait_for) if isinstance(wait_for, dict) else {}
        for leaf in leaf_wait_for_conditions(wf_d):
            wait_type = leaf_wait_type(leaf)
            wait_types[wait_type] = wait_types.get(wait_type, 0) + 1
        if str(step.get("intent") or "").strip().lower() in GENERIC_INTENTS:
            generic_intent_count += 1
    return {
        "event_counts": {
            "raw": len(raw),
            "normalized": len(normalized),
            "compiled": len(steps),
            "removed_during_compile": max(0, len(normalized) - len(steps)),
        },
        "validation_summary": {"wait_types": wait_types},
        "intent_summary": {"generic_intents": generic_intent_count, "specific_intents": len(steps) - generic_intent_count},
    }


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/record")
async def start_record(body: StartRecordBody) -> dict[str, Any]:
    """Start a headed Chromium session with in-page multi-signal capture."""
    sess = registry.create(str(body.start_url))
    metrics.inc("recordings_started")
    try:
        await sess.start()
    except NotImplementedError as exc:
        registry.pop(sess.session_id)
        raise HTTPException(
            status_code=500,
            detail=(
                "Playwright could not launch on this event loop. "
                "Restart uvicorn after latest code changes so Windows uses a Proactor event loop."
            ),
        ) from exc
    except RuntimeError as exc:
        registry.pop(sess.session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception:
        registry.pop(sess.session_id)
        raise
    return {"session_id": sess.session_id, "start_url": str(body.start_url)}


@router.get("/record/{session_id}/events")
def list_record_events(session_id: str) -> dict[str, Any]:
    sess = registry.get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Unknown session_id")
    evs = sess.snapshot_events()
    return {"session_id": session_id, "events": evs, "errors": sess.binding_errors}


@router.get("/record/{session_id}/status")
def record_status(session_id: str) -> dict[str, Any]:
    sess = registry.get(session_id)
    if not sess:
        stored_events = read_session_events(session_id)
        if not stored_events:
            raise HTTPException(status_code=404, detail="Unknown session_id")
        return {
            "session_id": session_id,
            "browser_open": False,
            "event_count": len(stored_events),
            "ended_by_user": True,
            "binding_errors": [],
        }
    return sess.status()


@router.post("/record/{session_id}/stop")
async def stop_record(session_id: str) -> dict[str, str]:
    stopped = await registry.remove(session_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Unknown session_id")
    metrics.inc("recordings_stopped")
    return {"session_id": session_id, "status": "stopped"}


@router.post("/compile")
async def compile_skill(body: CompileBody) -> dict[str, Any]:
    """Run Phase 2 pipeline + Phase 3 compiler; persist JSON skill package."""
    metrics.inc("compile_attempts")
    raw = _load_events_for_compile(body.session_id)
    if not raw:
        metrics.inc("compile_failures")
        raise HTTPException(
            status_code=400,
            detail="No events for this session. Poll GET /record/{id}/events or use a stopped session with events.jsonl.",
        )
    skill_title = body.skill_title.strip()
    if not skill_title:
        metrics.inc("compile_failures")
        raise HTTPException(status_code=400, detail="Skill Name is required.")
    skill_id = f"skill_{body.session_id}"
    try:
        normalized = run_pipeline(raw)
        existing = read_skill(skill_id)
        if existing:
            version = int((existing.get("meta") or {}).get("version") or 0) + 1
        else:
            version = 1
        package = compile_skill_package(
            normalized,
            skill_id=skill_id,
            source_session_id=body.session_id,
            title=skill_title,
            version=version,
        )
        audit_report, hard_failures = _build_audit_report(package.skills[0].steps)
        if hard_failures:
            metrics.inc("compile_failures")
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "compile_failed_static_audit",
                    "hard_failures": hard_failures,
                },
            )
        write_skill(skill_id, package.model_dump(mode="json"))
        metrics.inc("compile_successes")
        metrics.inc("fallback_usage", len(package.skills[0].steps))
    except HTTPException:
        raise
    except VisionAnchorGenerationError as exc:
        metrics.inc("compile_failures")
        raise HTTPException(status_code=422, detail=exc.api_detail()) from exc
    except Exception as exc:
        metrics.inc("compile_failures")
        raise HTTPException(status_code=500, detail=f"compile_failed: {exc!s}") from exc

    return {
        "skill_id": skill_id,
        "version": version,
        "step_count": len(package.skills[0].steps),
        "audit_status": "passed",
    }


@router.get("/compile-preview/{session_id}")
async def compile_preview(session_id: str) -> dict[str, Any]:
    """Build a non-persistent V3 preview + before/after compile diff."""
    raw = _load_events_for_compile(session_id)
    if not raw:
        raise HTTPException(status_code=400, detail="No events for this session.")
    skill_id = f"skill_{session_id}"
    normalized = run_pipeline(raw)
    try:
        package = compile_skill_package(
            normalized,
            skill_id=skill_id,
            source_session_id=session_id,
            title=skill_id,
            version=1,
        )
    except VisionAnchorGenerationError as exc:
        raise HTTPException(status_code=422, detail=exc.api_detail()) from exc
    package_json = package.model_dump(mode="json")
    steps = ((package_json.get("skills") or [{}])[0].get("steps") or [])
    _, hard_failures = _build_audit_report(package.skills[0].steps)
    diff_report = _build_preview_diff(raw, normalized, steps)
    return {
        "session_id": session_id,
        "skill_id": skill_id,
        "compiled_json": package_json,
        "diff_report": diff_report,
        "static_audit": {
            "status": "failed" if hard_failures else "passed",
            "hard_failures": hard_failures,
        },
    }


@router.get("/skill/{skill_id}")
def get_skill(skill_id: str) -> dict[str, Any]:
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    return doc


@router.post("/update-step")
def update_step(body: UpdateStepBody) -> dict[str, Any]:
    """Merge a deterministic patch into one step; bump version; run structural revalidation."""
    metrics.inc("update_step_attempts")
    doc = read_skill(body.skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    try:
        new_doc = apply_step_patch(doc, body.step_index, body.patch, assist_llm=body.assist_llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    steps = (new_doc.get("skills") or [{}])[0].get("steps") or []
    if body.step_index < 0 or body.step_index >= len(steps):
        raise HTTPException(status_code=400, detail="step_index_out_of_range")
    reval = revalidate_step(dict(steps[body.step_index]))
    write_skill(body.skill_id, new_doc)
    metrics.inc("update_step_successes")
    return {
        "skill_id": body.skill_id,
        "meta": new_doc.get("meta"),
        "revalidation": reval,
    }


@router.get("/metrics")
def get_metrics() -> dict[str, Any]:
    snap = metrics.snapshot()
    alerts: list[dict[str, str]] = []
    if snap["compile_attempts"] > 5 and snap["compile_ok_rate"] < 0.5:
        alerts.append(
            {
                "type": "compile_regression",
                "detail": "Compile success rate dropped; consider re-recording or 1-click fixes.",
            }
        )
    snap["alerts"] = alerts
    return snap
