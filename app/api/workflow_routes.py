"""Skill workflow editor API — DTO workflow view, PATCH step/skill, validate, assets, reorder."""

from __future__ import annotations

import mimetypes
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.compiler.build import compile_skill_package
from app.compiler.patch import apply_step_patch, revalidate_step
from app.editor.assets import resolve_skill_asset
from app.editor.patch_gate import validate_editor_patch
from app.editor.workflow_service import (
    build_workflow_response,
    delete_step_at,
    ensure_initial_navigation_step,
    insert_step_after,
    merge_skill_inputs,
    reorder_steps,
    replace_string_literals_in_skill_document,
    validate_skill_document,
)
from app.editor.recording_visual import (
    apply_recording_event_visual_to_step_or_raise,
    clear_step_visual_screenshots_or_raise,
    screenshot_items_for_skill,
    update_step_visual_bbox_and_regenerate_anchors_or_raise,
)
from app.llm.anchor_vision_llm import VisionAnchorGenerationError
from app.metrics.store import metrics
from app.pipeline.run import run_pipeline
from app.policy.bundle import get_policy_bundle
from app.storage.json_store import delete_skill, list_skill_summaries, read_skill, write_skill
from app.storage.session_events import read_session_events

from app.api.routes import _build_audit_report

router = APIRouter(prefix="/skills", tags=["skills-workflow"])


def _asset_base_url(request: Request) -> str:
    path = request.url.path
    if path.startswith("/api/v1/"):
        return "/api/v1"
    return ""


class StepPatchBody(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)
    assist_llm: bool = False


class ReorderBody(BaseModel):
    new_order: list[int]


class InsertStepBody(BaseModel):
    action_kind: str = Field(..., min_length=1)
    insert_after: int | None = None


class SkillPatchBody(BaseModel):
    inputs: list[dict[str, Any]] | None = None
    title: str | None = None


class WorkflowLiteralReplaceBody(BaseModel):
    find: str = Field(..., min_length=1)
    replace_with: str = ""


class CompileUpdatedBody(BaseModel):
    skill_title: str | None = None


class ApplyRecordingVisualBody(BaseModel):
    """Pick a raw session event index from ``recording-screenshots`` and attach its frame to this step."""

    event_index: int = Field(ge=0)


class VisualBboxBody(BaseModel):
    """CSS-pixel target region drawn over a step screenshot."""

    x: float = Field(ge=0)
    y: float = Field(ge=0)
    w: float = Field(gt=0)
    h: float = Field(gt=0)


@router.get("", summary="List stored skill packages (newest first)")
def list_skills() -> dict[str, Any]:
    return {"skills": list_skill_summaries()}


@router.get("/{skill_id}/recording-screenshots")
def list_recording_screenshots(skill_id: str, request: Request) -> dict[str, Any]:
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    session_id, items = screenshot_items_for_skill(skill_id, doc, asset_base_url=_asset_base_url(request))
    return {"skill_id": skill_id, "session_id": session_id, "items": items}


@router.get("/{skill_id}/workflow")
def get_workflow(skill_id: str, request: Request) -> dict[str, Any]:
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    doc, changed = ensure_initial_navigation_step(doc)
    if changed:
        write_skill(skill_id, doc)
    wf = build_workflow_response(skill_id, doc, asset_base_url=_asset_base_url(request))
    return wf.model_dump(mode="json")


@router.delete("/{skill_id}")
def delete_skill_package(skill_id: str) -> dict[str, Any]:
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    title = str((doc.get("meta") or {}).get("title") or skill_id)
    if not delete_skill(skill_id):
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    return {"skill_id": skill_id, "title": title, "deleted": True}


@router.patch("/{skill_id}/steps/{step_index}")
def patch_step(skill_id: str, step_index: int, body: StepPatchBody, request: Request) -> dict[str, Any]:
    metrics.inc("workflow_patch_step_attempts")
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    steps = (doc.get("skills") or [{}])[0].get("steps") or []
    if step_index < 0 or step_index >= len(steps):
        raise HTTPException(status_code=400, detail="step_index_out_of_range")
    step = dict(steps[step_index])
    policy = get_policy_bundle().data
    try:
        validate_editor_patch(step, body.patch, policy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        new_doc = apply_step_patch(doc, step_index, body.patch, assist_llm=body.assist_llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    steps_after = (new_doc.get("skills") or [{}])[0].get("steps") or []
    reval = revalidate_step(dict(steps_after[step_index]))
    write_skill(skill_id, new_doc)
    metrics.inc("workflow_patch_step_successes")
    wf = build_workflow_response(skill_id, new_doc, asset_base_url=_asset_base_url(request))
    return {
        "skill_id": skill_id,
        "meta": new_doc.get("meta"),
        "revalidation": reval,
        "workflow": wf.model_dump(mode="json"),
    }


@router.post("/{skill_id}/steps/{step_index}/apply-recording-visual")
def post_apply_recording_visual(
    skill_id: str,
    step_index: int,
    body: ApplyRecordingVisualBody,
    request: Request,
) -> dict[str, Any]:
    """Attach a recording screenshot (+ bbox) and regenerate vision-backed anchors via the LLM."""
    metrics.inc("workflow_apply_recording_visual_attempts")
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    steps = ((doc.get("skills") or [{}])[0]).get("steps") or []
    if step_index < 0 or step_index >= len(steps):
        raise HTTPException(status_code=400, detail="step_index_out_of_range")
    try:
        new_doc = apply_recording_event_visual_to_step_or_raise(doc, step_index, body.event_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VisionAnchorGenerationError as exc:
        raise HTTPException(status_code=422, detail=exc.api_detail()) from exc

    steps_after = (new_doc.get("skills") or [{}])[0].get("steps") or []
    rev = revalidate_step(dict(steps_after[step_index]))
    write_skill(skill_id, new_doc)
    metrics.inc("workflow_apply_recording_visual_successes")
    wf = build_workflow_response(skill_id, new_doc, asset_base_url=_asset_base_url(request))
    return {
        "skill_id": skill_id,
        "meta": new_doc.get("meta"),
        "revalidation": rev,
        "workflow": wf.model_dump(mode="json"),
    }


@router.post("/{skill_id}/steps/{step_index}/visual-bbox")
def post_update_visual_bbox(
    skill_id: str,
    step_index: int,
    body: VisualBboxBody,
    request: Request,
) -> dict[str, Any]:
    """Save a manually drawn visual bbox and regenerate vision-backed anchors for the step."""
    metrics.inc("workflow_update_visual_bbox_attempts")
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    steps = ((doc.get("skills") or [{}])[0]).get("steps") or []
    if step_index < 0 or step_index >= len(steps):
        raise HTTPException(status_code=400, detail="step_index_out_of_range")
    try:
        new_doc = update_step_visual_bbox_and_regenerate_anchors_or_raise(
            doc,
            step_index,
            body.model_dump(mode="json"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VisionAnchorGenerationError as exc:
        raise HTTPException(status_code=422, detail=exc.api_detail()) from exc

    steps_after = (new_doc.get("skills") or [{}])[0].get("steps") or []
    rev = revalidate_step(dict(steps_after[step_index]))
    write_skill(skill_id, new_doc)
    metrics.inc("workflow_update_visual_bbox_successes")
    wf = build_workflow_response(skill_id, new_doc, asset_base_url=_asset_base_url(request))
    return {
        "skill_id": skill_id,
        "meta": new_doc.get("meta"),
        "revalidation": rev,
        "workflow": wf.model_dump(mode="json"),
    }


@router.post("/{skill_id}/steps/{step_index}/clear-step-visual")
def post_clear_step_visual(
    skill_id: str,
    step_index: int,
    request: Request,
) -> dict[str, Any]:
    """Remove screenshot paths from ``signals.visual`` and clear vision-backed anchors."""
    metrics.inc("workflow_clear_step_visual_attempts")
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    steps = ((doc.get("skills") or [{}])[0]).get("steps") or []
    if step_index < 0 or step_index >= len(steps):
        raise HTTPException(status_code=400, detail="step_index_out_of_range")
    try:
        new_doc = clear_step_visual_screenshots_or_raise(doc, step_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    steps_after = (new_doc.get("skills") or [{}])[0].get("steps") or []
    rev = revalidate_step(dict(steps_after[step_index]))
    write_skill(skill_id, new_doc)
    metrics.inc("workflow_clear_step_visual_successes")
    wf = build_workflow_response(skill_id, new_doc, asset_base_url=_asset_base_url(request))
    return {
        "skill_id": skill_id,
        "meta": new_doc.get("meta"),
        "revalidation": rev,
        "workflow": wf.model_dump(mode="json"),
    }


@router.patch("/{skill_id}")
def patch_skill_package(skill_id: str, body: SkillPatchBody) -> dict[str, Any]:
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    if body.title is not None and not body.title.strip():
        raise HTTPException(status_code=400, detail="Skill Name is required.")
    inputs = body.inputs if body.inputs is not None else list(doc.get("inputs") or [])
    new_doc = merge_skill_inputs(doc, inputs, body.title.strip() if body.title is not None else None)
    write_skill(skill_id, new_doc)
    return {"skill_id": skill_id, "meta": new_doc.get("meta"), "inputs": new_doc.get("inputs")}


@router.post("/{skill_id}/workflow:replace-literals")
def post_workflow_replace_literals(
    skill_id: str,
    body: WorkflowLiteralReplaceBody,
    request: Request,
) -> dict[str, Any]:
    """Replace a literal substring in every string field of the skill document (full JSON)."""
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    try:
        new_doc = replace_string_literals_in_skill_document(doc, body.find, body.replace_with)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_skill(skill_id, new_doc)
    wf = build_workflow_response(skill_id, new_doc, asset_base_url=_asset_base_url(request))
    return {"skill_id": skill_id, "meta": new_doc.get("meta"), "workflow": wf.model_dump(mode="json")}


@router.post("/{skill_id}/steps:reorder")
def post_reorder(skill_id: str, body: ReorderBody, request: Request) -> dict[str, Any]:
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    try:
        new_doc = reorder_steps(doc, body.new_order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_skill(skill_id, new_doc)
    wf = build_workflow_response(skill_id, new_doc, asset_base_url=_asset_base_url(request))
    return {"skill_id": skill_id, "meta": new_doc.get("meta"), "workflow": wf.model_dump(mode="json")}


@router.post("/{skill_id}/steps")
def post_insert_step(skill_id: str, body: InsertStepBody, request: Request) -> dict[str, Any]:
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    try:
        new_doc = insert_step_after(doc, body.action_kind, body.insert_after)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_skill(skill_id, new_doc)
    wf = build_workflow_response(skill_id, new_doc, asset_base_url=_asset_base_url(request))
    return {"skill_id": skill_id, "meta": new_doc.get("meta"), "workflow": wf.model_dump(mode="json")}


@router.delete("/{skill_id}/steps/{step_index}")
def delete_step(skill_id: str, step_index: int, request: Request) -> dict[str, Any]:
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    try:
        new_doc = delete_step_at(doc, step_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_skill(skill_id, new_doc)
    wf = build_workflow_response(skill_id, new_doc, asset_base_url=_asset_base_url(request))
    return {"skill_id": skill_id, "meta": new_doc.get("meta"), "workflow": wf.model_dump(mode="json")}


@router.post("/{skill_id}/validate")
def post_validate(skill_id: str) -> dict[str, Any]:
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    return validate_skill_document(doc)


@router.post("/{skill_id}/compile-updated")
async def compile_updated(skill_id: str, body: CompileUpdatedBody) -> dict[str, Any]:
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    session_id = (doc.get("meta") or {}).get("source_session_id")
    if not session_id:
        raise HTTPException(
            status_code=409,
            detail="no_source_session_id_on_skill_use_patch_revalidate_instead",
        )
    raw = read_session_events(str(session_id))
    if not raw:
        raise HTTPException(
            status_code=409,
            detail="session_events_missing_cannot_full_recompile",
        )
    try:
        normalized = run_pipeline(raw)
        version = int((doc.get("meta") or {}).get("version") or 0) + 1
        title_override = body.skill_title.strip() if body.skill_title is not None else None
        if body.skill_title is not None and not title_override:
            raise HTTPException(status_code=400, detail="Skill Name is required.")
        title = title_override or str((doc.get("meta") or {}).get("title") or skill_id)
        package = compile_skill_package(
            normalized,
            skill_id=skill_id,
            source_session_id=str(session_id),
            title=title,
            version=version,
        )
        _, hard_failures = _build_audit_report(package.skills[0].steps)
        if hard_failures:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "compile_failed_static_audit",
                    "hard_failures": hard_failures,
                },
            )
        package_json = package.model_dump(mode="json")
        write_skill(skill_id, package_json)
    except HTTPException:
        raise
    except VisionAnchorGenerationError as exc:
        raise HTTPException(status_code=422, detail=exc.api_detail()) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"compile_updated_failed: {exc!s}") from exc
    return {"skill_id": skill_id, "version": package_json["meta"]["version"], "step_count": len(package.skills[0].steps)}


@router.get("/{skill_id}/assets")
def get_skill_asset(skill_id: str, path: str) -> FileResponse:
    if read_skill(skill_id) is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    try:
        p = resolve_skill_asset(path)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_asset_path") from None
    if not p.is_file():
        raise HTTPException(status_code=404, detail="asset_not_found")
    media = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    return FileResponse(str(p), media_type=media)
