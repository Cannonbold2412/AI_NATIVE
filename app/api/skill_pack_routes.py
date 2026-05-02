"""Skill Pack Builder API routes."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.skill_pack_builder import build_skill_package, build_skill_package_zip
from app.storage.skill_packages import delete_skill_package, list_skill_package_summaries, read_skill_package_files

router = APIRouter(prefix="/skill-pack", tags=["skill-pack"])


class SkillPackBuildBody(BaseModel):
    json_text: str = Field(..., min_length=2)


class SkillPackExportBody(BaseModel):
    name: str = Field(default="generated_skill", min_length=1)
    skill_md: str = Field(..., min_length=1)
    skill_json: str | None = None
    inputs_json: str | None = None
    manifest_json: str = Field(..., min_length=2)
    execution_json: str | None = None
    recovery_json: str | None = None
    execution_md: str | None = None
    execution_plan_json: str | None = None


@router.get("/packages")
def get_skill_packages() -> dict[str, Any]:
    return {"packages": list_skill_package_summaries()}


@router.get("/{package_name}")
def get_skill_pack_files(package_name: str) -> dict[str, Any]:
    files = read_skill_package_files(package_name)
    if not files:
        raise HTTPException(status_code=404, detail="Skill package not found.")
    return {"package_name": package_name, "files": files}


@router.post("/build")
def post_build_skill_pack(body: SkillPackBuildBody) -> dict[str, Any]:
    try:
        return build_skill_package(body.json_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/export")
def post_export_skill_pack(body: SkillPackExportBody) -> StreamingResponse:
    try:
        filename, payload = build_skill_package_zip(
            package_name=body.name,
            skill_md=body.skill_md,
            skill_json=body.skill_json or "{}",
            inputs_json=body.inputs_json or "",
            manifest_json=body.manifest_json,
            execution_md=body.execution_md or "",
            execution_plan_json=body.execution_plan_json or "",
            execution_json=body.execution_json or "",
            recovery_json=body.recovery_json or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(BytesIO(payload), media_type="application/zip", headers=headers)


@router.get("/{package_name}/download")
def get_download_skill_pack(package_name: str) -> StreamingResponse:
    files = read_skill_package_files(package_name)
    if not files:
        raise HTTPException(status_code=404, detail="Skill package not found.")
    try:
        filename, payload = build_skill_package_zip(
            package_name=package_name,
            skill_md=files.get("skill.md", ""),
            skill_json=files.get("skill.json", ""),
            inputs_json=files.get("inputs.json", ""),
            manifest_json=files.get("manifest.json", ""),
            execution_md=files.get("execution.md", ""),
            execution_plan_json=files.get("execution_plan.json", ""),
            execution_json=files.get("execution.json", ""),
            recovery_json=files.get("recovery.json", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(BytesIO(payload), media_type="application/zip", headers=headers)


@router.delete("/{package_name}")
def delete_saved_skill_pack(package_name: str) -> dict[str, Any]:
    if not delete_skill_package(package_name):
        raise HTTPException(status_code=404, detail="Skill package not found.")
    return {"package_name": package_name, "deleted": True}
