"""Skill Pack Builder API routes."""

from __future__ import annotations

import asyncio
import json
from io import BytesIO
from queue import SimpleQueue
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.skill_pack_builder import (
    SkillPackBuildUserError,
    append_workflow_to_skill_package,
    build_skill_package,
    build_skill_package_zip,
    slugify_skill_package_folder_name,
    zip_skill_bundle_from_disk,
)
from app.storage.skill_packages import (
    delete_skill_package_bundle,
    delete_skill_package_workflow,
    list_skill_bundle_summaries,
    package_bundle_root_name,
    read_skill_package_bundle_files,
    read_skill_package_files,
    rename_package_bundle_root,
    rename_skill_package_bundle,
    rename_skill_package_workflow,
)

router = APIRouter(prefix="/skill-pack", tags=["skill-pack"])

_SKILL_PACK_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse_data_line(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n".encode("utf-8")


async def _skill_pack_build_sse_events(
    *,
    json_text: str,
    package_name: str | None,
    bundle_slug: str,
) -> AsyncIterator[bytes]:
    q: SimpleQueue[tuple[str, Any]] = SimpleQueue()

    def realtime_sink(entry: dict[str, Any]) -> None:
        q.put(("log", entry))

    def runner() -> None:
        try:
            out = build_skill_package(
                json_text,
                package_name=package_name,
                bundle_slug=bundle_slug,
                realtime_sink=realtime_sink,
            )
            q.put(("ok", out))
        except SkillPackBuildUserError as exc:
            q.put(("fail", {"message": str(exc), "build_log": exc.build_log}))
        except Exception as exc:  # noqa: BLE001
            q.put(("fail", {"message": str(exc), "build_log": []}))

    asyncio.get_running_loop().run_in_executor(None, runner)

    while True:
        kind, data = await asyncio.to_thread(q.get)
        if kind == "log":
            yield _sse_data_line({"event": "log", "entry": data})
        elif kind == "ok":
            yield _sse_data_line({"event": "done", "result": data})
            return
        elif kind == "fail":
            fail = dict(data)
            fail["event"] = "error"
            yield _sse_data_line(fail)
            return


async def _skill_pack_append_sse_events(
    *,
    bundle_slug: str,
    json_text: str,
    appended_package_name: str | None,
) -> AsyncIterator[bytes]:
    q: SimpleQueue[tuple[str, Any]] = SimpleQueue()

    def realtime_sink(entry: dict[str, Any]) -> None:
        q.put(("log", entry))

    def runner() -> None:
        try:
            out = append_workflow_to_skill_package(
                bundle_slug,
                json_text,
                appended_package_name=appended_package_name,
                realtime_sink=realtime_sink,
            )
            q.put(("ok", out))
        except SkillPackBuildUserError as exc:
            q.put(("fail", {"message": str(exc), "build_log": exc.build_log}))
        except Exception as exc:  # noqa: BLE001
            q.put(("fail", {"message": str(exc), "build_log": []}))

    asyncio.get_running_loop().run_in_executor(None, runner)

    while True:
        kind, data = await asyncio.to_thread(q.get)
        if kind == "log":
            yield _sse_data_line({"event": "log", "entry": data})
        elif kind == "ok":
            yield _sse_data_line({"event": "done", "result": data})
            return
        elif kind == "fail":
            fail = dict(data)
            fail["event"] = "error"
            yield _sse_data_line(fail)
            return


class SkillPackBuildBody(BaseModel):
    json_text: str = Field(..., min_length=2)
    package_name: str | None = None
    """Optional workflow folder slug inside the bundle."""
    bundle_name: str = Field(default="default")
    """Named skill package under output/skill_package/<bundle_name>/ (POST /skill-pack/build only)."""


class SkillPackRenameBody(BaseModel):
    new_name: str = Field(..., min_length=1)


class SkillPackBundleRootBody(BaseModel):
    bundle_root: str = Field(..., min_length=1)


class SkillPackExportBody(BaseModel):
    name: str = Field(default="generated_skill", min_length=1)
    bundle_name: str | None = Field(default="default")
    skill_md: str = Field(..., min_length=1)
    inputs_json: str = Field(..., min_length=2)
    manifest_json: str = Field(..., min_length=2)
    execution_json: str = Field(..., min_length=2)
    recovery_json: str = Field(..., min_length=2)


@router.get("/packages")
def get_skill_packages() -> dict[str, Any]:
    return {"packages": list_skill_bundle_summaries(), "bundle_root": package_bundle_root_name()}


@router.patch("/bundle-root")
def patch_skill_pack_bundle_root(body: SkillPackBundleRootBody) -> dict[str, Any]:
    slug = slugify_skill_package_folder_name(body.bundle_root)
    try:
        new_name = rename_package_bundle_root(slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"bundle_root": new_name}


def _skill_pack_http_user_error(exc: SkillPackBuildUserError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"message": str(exc), "build_log": getattr(exc, "build_log", None) or []},
    )


@router.post("/bundles/{bundle_slug}/build")
def post_build_skill_pack_for_bundle(bundle_slug: str, body: SkillPackBuildBody) -> dict[str, Any]:
    try:
        return build_skill_package(
            body.json_text,
            package_name=body.package_name,
            bundle_slug=bundle_slug,
        )
    except SkillPackBuildUserError as exc:
        raise _skill_pack_http_user_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bundles/{bundle_slug}/append")
def post_append_skill_pack_for_bundle(bundle_slug: str, body: SkillPackBuildBody) -> dict[str, Any]:
    try:
        return append_workflow_to_skill_package(
            bundle_slug,
            body.json_text,
            appended_package_name=body.package_name,
        )
    except SkillPackBuildUserError as exc:
        raise _skill_pack_http_user_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bundles/{bundle_slug}/append/stream")
async def post_append_skill_pack_stream_for_bundle(bundle_slug: str, body: SkillPackBuildBody) -> StreamingResponse:
    """Same as append but streams ``build_log`` rows as SSE (``log`` events) while compiling."""

    return StreamingResponse(
        _skill_pack_append_sse_events(
            bundle_slug=bundle_slug,
            json_text=body.json_text,
            appended_package_name=body.package_name,
        ),
        media_type="text/event-stream",
        headers=dict(_SKILL_PACK_STREAM_HEADERS),
    )


@router.get("/bundles/{bundle_slug}")
def get_skill_pack_bundle_files(bundle_slug: str) -> dict[str, Any]:
    files = read_skill_package_bundle_files(bundle_slug)
    if not files:
        raise HTTPException(status_code=404, detail="Skill package bundle not found.")
    return {"package_name": bundle_slug, "files": files}


@router.get("/bundles/{bundle_slug}/workflows/{workflow_slug}")
def get_skill_pack_workflow_files(bundle_slug: str, workflow_slug: str) -> dict[str, Any]:
    files = read_skill_package_files(bundle_slug, workflow_slug)
    if not files:
        raise HTTPException(status_code=404, detail="Workflow not found in this bundle.")
    return {"package_name": workflow_slug, "bundle_name": bundle_slug, "files": files}


@router.get("/bundles/{bundle_slug}/download")
def get_download_skill_pack_bundle(bundle_slug: str) -> StreamingResponse:
    try:
        filename, payload = zip_skill_bundle_from_disk(bundle_slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(BytesIO(payload), media_type="application/zip", headers=headers)


@router.delete("/bundles/{bundle_slug}")
def delete_saved_skill_pack_bundle(bundle_slug: str) -> dict[str, Any]:
    if not delete_skill_package_bundle(bundle_slug):
        raise HTTPException(status_code=404, detail="Skill package bundle not found.")
    return {"package_name": bundle_slug, "deleted": True}


@router.patch("/bundles/{bundle_slug}")
def patch_rename_skill_pack_bundle(bundle_slug: str, body: SkillPackRenameBody) -> dict[str, Any]:
    slug = slugify_skill_package_folder_name(body.new_name)
    try:
        rename_skill_package_bundle(bundle_slug, slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Skill package bundle not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"package_name": slug, "previous_name": bundle_slug}


@router.delete("/bundles/{bundle_slug}/workflows/{workflow_slug}")
def delete_skill_pack_workflow(bundle_slug: str, workflow_slug: str) -> dict[str, Any]:
    if not delete_skill_package_workflow(bundle_slug, workflow_slug):
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return {"bundle_name": bundle_slug, "package_name": workflow_slug, "deleted": True}


@router.patch("/bundles/{bundle_slug}/workflows/{workflow_slug}")
def patch_rename_skill_pack_workflow(bundle_slug: str, workflow_slug: str, body: SkillPackRenameBody) -> dict[str, Any]:
    slug = slugify_skill_package_folder_name(body.new_name)
    try:
        rename_skill_package_workflow(bundle_slug, workflow_slug, slug)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Workflow not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"package_name": slug, "previous_name": workflow_slug}


@router.post("/build")
def post_build_skill_pack(body: SkillPackBuildBody) -> dict[str, Any]:
    """Build into ``output/skill_package/<bundle_name>/`` (defaults to ``default``)."""

    try:
        return build_skill_package(
            body.json_text,
            package_name=body.package_name,
            bundle_slug=body.bundle_name,
        )
    except SkillPackBuildUserError as exc:
        raise _skill_pack_http_user_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/build/stream")
async def post_build_skill_pack_stream(body: SkillPackBuildBody) -> StreamingResponse:
    """Same as ``POST /skill-pack/build`` but streams ``build_log`` rows as SSE as they occur."""

    return StreamingResponse(
        _skill_pack_build_sse_events(
            json_text=body.json_text,
            package_name=body.package_name,
            bundle_slug=body.bundle_name,
        ),
        media_type="text/event-stream",
        headers=dict(_SKILL_PACK_STREAM_HEADERS),
    )


@router.post("/bundles/{bundle_slug}/build/stream")
async def post_bundle_build_skill_pack_stream(bundle_slug: str, body: SkillPackBuildBody) -> StreamingResponse:
    return StreamingResponse(
        _skill_pack_build_sse_events(
            json_text=body.json_text,
            package_name=body.package_name,
            bundle_slug=bundle_slug,
        ),
        media_type="text/event-stream",
        headers=dict(_SKILL_PACK_STREAM_HEADERS),
    )


@router.post("/export")
def post_export_skill_pack(body: SkillPackExportBody) -> StreamingResponse:
    bundle = body.bundle_name or "default"
    try:
        filename, payload = build_skill_package_zip(
            package_name=body.name,
            skill_md=body.skill_md,
            inputs_json=body.inputs_json,
            manifest_json=body.manifest_json,
            execution_json=body.execution_json,
            recovery_json=body.recovery_json,
            skill_pack_bundle=bundle,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(BytesIO(payload), media_type="application/zip", headers=headers)
