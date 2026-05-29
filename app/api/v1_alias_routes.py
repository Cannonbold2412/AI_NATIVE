"""Plain `/api/v1` resource aliases for the production API contract."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.routes import (
    StartRecordBody,
    list_record_events,
    record_status,
    start_record,
    stop_record,
)
from app.api.skill_pack_routes import (
    SkillPackBuildBody,
    SkillPackBundleRootBody,
    SkillPackExportBody,
    SkillPackRenameBody,
    delete_saved_skill_pack_bundle,
    delete_skill_pack_workflow,
    get_download_skill_pack_bundle,
    get_skill_pack_bundle_files,
    get_skill_pack_workflow_files,
    get_skill_packages,
    patch_rename_skill_pack_bundle,
    patch_rename_skill_pack_workflow,
    patch_skill_pack_bundle_root,
    post_append_skill_pack_for_bundle,
    post_append_skill_pack_stream_for_bundle,
    post_build_skill_pack,
    post_build_skill_pack_for_bundle,
    post_build_skill_pack_stream,
    post_bundle_build_skill_pack_stream,
    post_export_skill_pack,
)

router = APIRouter(tags=["v1-aliases"])


@router.post("/recordings")
async def post_recording(body: StartRecordBody) -> dict[str, Any]:
    return await start_record(body)


@router.get("/recordings/{session_id}/events")
def get_recording_events(session_id: str) -> dict[str, Any]:
    return list_record_events(session_id)


@router.get("/recordings/{session_id}/status")
def get_recording_status(session_id: str) -> dict[str, Any]:
    return record_status(session_id)


@router.post("/recordings/{session_id}/stop")
async def post_recording_stop(session_id: str) -> dict[str, str]:
    return await stop_record(session_id)


@router.get("/packages")
def get_packages() -> dict[str, Any]:
    return get_skill_packages()


@router.patch("/packages/bundle-root")
def patch_packages_bundle_root(body: SkillPackBundleRootBody) -> dict[str, Any]:
    return patch_skill_pack_bundle_root(body)


@router.post("/packages/build")
def post_packages_build(body: SkillPackBuildBody) -> dict[str, Any]:
    return post_build_skill_pack(body)


@router.post("/packages/build/stream")
async def post_packages_build_stream(body: SkillPackBuildBody) -> StreamingResponse:
    return await post_build_skill_pack_stream(body)


@router.post("/packages/export")
def post_packages_export(body: SkillPackExportBody) -> StreamingResponse:
    return post_export_skill_pack(body)


@router.get("/packages/bundles/{bundle_slug}")
def get_package_bundle_files(bundle_slug: str) -> dict[str, Any]:
    return get_skill_pack_bundle_files(bundle_slug)


@router.get("/packages/bundles/{bundle_slug}/download")
def get_package_bundle_download(bundle_slug: str) -> StreamingResponse:
    return get_download_skill_pack_bundle(bundle_slug)


@router.delete("/packages/bundles/{bundle_slug}")
def delete_package_bundle(bundle_slug: str) -> dict[str, Any]:
    return delete_saved_skill_pack_bundle(bundle_slug)


@router.patch("/packages/bundles/{bundle_slug}")
def patch_package_bundle(bundle_slug: str, body: SkillPackRenameBody) -> dict[str, Any]:
    return patch_rename_skill_pack_bundle(bundle_slug, body)


@router.post("/packages/bundles/{bundle_slug}/build")
def post_package_bundle_build(bundle_slug: str, body: SkillPackBuildBody) -> dict[str, Any]:
    return post_build_skill_pack_for_bundle(bundle_slug, body)


@router.post("/packages/bundles/{bundle_slug}/build/stream")
async def post_package_bundle_build_stream(bundle_slug: str, body: SkillPackBuildBody) -> StreamingResponse:
    return await post_bundle_build_skill_pack_stream(bundle_slug, body)


@router.post("/packages/bundles/{bundle_slug}/append")
def post_package_bundle_append(bundle_slug: str, body: SkillPackBuildBody) -> dict[str, Any]:
    return post_append_skill_pack_for_bundle(bundle_slug, body)


@router.post("/packages/bundles/{bundle_slug}/append/stream")
async def post_package_bundle_append_stream(bundle_slug: str, body: SkillPackBuildBody) -> StreamingResponse:
    return await post_append_skill_pack_stream_for_bundle(bundle_slug, body)


@router.get("/packages/bundles/{bundle_slug}/workflows/{workflow_slug}")
def get_package_bundle_workflow_files(bundle_slug: str, workflow_slug: str) -> dict[str, Any]:
    return get_skill_pack_workflow_files(bundle_slug, workflow_slug)


@router.delete("/packages/bundles/{bundle_slug}/workflows/{workflow_slug}")
def delete_package_bundle_workflow(bundle_slug: str, workflow_slug: str) -> dict[str, Any]:
    return delete_skill_pack_workflow(bundle_slug, workflow_slug)


@router.patch("/packages/bundles/{bundle_slug}/workflows/{workflow_slug}")
def patch_package_bundle_workflow(bundle_slug: str, workflow_slug: str, body: SkillPackRenameBody) -> dict[str, Any]:
    return patch_rename_skill_pack_workflow(bundle_slug, workflow_slug, body)


@router.get("/audit-events")
def list_audit_events() -> dict[str, Any]:
    return {"audit_events": []}
