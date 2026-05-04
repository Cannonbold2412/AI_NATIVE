"""Versioned job APIs for worker-backed operations and status streaming."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.routes import CompileBody, compile_skill
from app.api.skill_pack_routes import SkillPackBuildBody
from app.services.jobs import enqueue_job, job_store
from app.services.skill_pack_builder import build_skill_package

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _sse(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n".encode("utf-8")


@router.get("")
def list_jobs() -> dict[str, Any]:
    return {"jobs": [job.public() for job in job_store.list()]}


@router.get("/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown_job_id")
    return job.public()


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown_job_id")
    if job.status in {"succeeded", "failed", "canceled"}:
        return job.public()
    job_store.mark_canceled(job_id)
    return job_store.get(job_id).public()  # type: ignore[union-attr]


async def _job_events(job_id: str) -> AsyncIterator[bytes]:
    if job_store.get(job_id) is None:
        yield _sse({"event": "error", "message": "unknown_job_id"})
        return

    next_index = 0
    while True:
        events = job_store.events_after(job_id, next_index)
        for event in events:
            yield _sse(event)
        next_index += len(events)

        job = job_store.get(job_id)
        if job is None or job.status in {"succeeded", "failed", "canceled"}:
            return
        await asyncio.sleep(0.75)


@router.get("/{job_id}/events")
def stream_job_events(job_id: str) -> StreamingResponse:
    return StreamingResponse(
        _job_events(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/compile")
async def enqueue_compile_job(body: CompileBody) -> dict[str, Any]:
    job = await enqueue_job("compile_skill", lambda: compile_skill(body), resource_id=f"skill_{body.session_id}")
    return {"job_id": job.job_id, "status": job.status, "resource_id": job.resource_id}


@router.post("/packages/build")
async def enqueue_package_build_job(body: SkillPackBuildBody) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        return await asyncio.to_thread(
            build_skill_package,
            body.json_text,
            package_name=body.package_name,
            bundle_slug=body.bundle_name,
        )

    job = await enqueue_job("package_build", run)
    return {"job_id": job.job_id, "status": job.status, "resource_id": job.resource_id}
