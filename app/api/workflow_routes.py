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
    merge_skill_inputs,
    reorder_steps,
    validate_skill_document,
)
from app.metrics.store import metrics
from app.pipeline.run import run_pipeline
from app.policy.bundle import get_policy_bundle
from app.storage.json_store import list_skill_summaries, read_skill, write_skill
from app.storage.session_events import read_session_events

from app.api.routes import _build_audit_report

router = APIRouter(prefix="/skills", tags=["skills-workflow"])


def _asset_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


class StepPatchBody(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)
    assist_llm: bool = False


class ReorderBody(BaseModel):
    new_order: list[int]


class SkillPatchBody(BaseModel):
    inputs: list[dict[str, Any]] | None = None
    title: str | None = None


class CompileUpdatedBody(BaseModel):
    skill_title: str | None = None


@router.get("", summary="List stored skill packages (newest first)")
def list_skills() -> dict[str, Any]:
    return {"skills": list_skill_summaries()}


@router.get("/{skill_id}/workflow")
def get_workflow(skill_id: str, request: Request) -> dict[str, Any]:
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    wf = build_workflow_response(skill_id, doc, asset_base_url=_asset_base_url(request))
    return wf.model_dump(mode="json")


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


@router.patch("/{skill_id}")
def patch_skill_package(skill_id: str, body: SkillPatchBody) -> dict[str, Any]:
    doc = read_skill(skill_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Unknown skill_id")
    inputs = body.inputs if body.inputs is not None else list(doc.get("inputs") or [])
    new_doc = merge_skill_inputs(doc, inputs, body.title)
    write_skill(skill_id, new_doc)
    return {"skill_id": skill_id, "meta": new_doc.get("meta"), "inputs": new_doc.get("inputs")}


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
        title = body.skill_title or str((doc.get("meta") or {}).get("title") or skill_id)
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
