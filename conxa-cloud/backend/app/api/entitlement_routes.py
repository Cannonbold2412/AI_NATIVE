"""Current entitlement meters and compile-credit reservation endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.entitlements import (
    EntitlementError,
    commit_compile_credit,
    current_entitlements,
    release_compile_credit,
    reserve_compile_credit,
)
from app.services.saas import ensure_principal, principal_from_request

router = APIRouter(tags=["entitlements"])


class ReserveCompileBody(BaseModel):
    reservation_id: str = Field(..., min_length=1, max_length=256)
    plugin_id: str = Field(default="", max_length=128)
    workflow_id: str = Field(default="", max_length=128)
    session_id: str = Field(default="", max_length=128)


class ReservationBody(BaseModel):
    reservation_id: str = Field(..., min_length=1, max_length=256)


def _principal(request: Request):
    principal = principal_from_request(request)
    ensure_principal(principal)
    return principal


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, EntitlementError):
        return HTTPException(status_code=exc.status_code, detail=exc.code)
    return HTTPException(status_code=503, detail="entitlements_unavailable")


@router.get("/entitlements/current")
def get_current_entitlements(request: Request) -> dict[str, Any]:
    try:
        return current_entitlements(_principal(request))
    except Exception as exc:  # noqa: BLE001
        raise _service_error(exc) from exc


@router.post("/usage/compile/reserve")
def post_compile_reserve(body: ReserveCompileBody, request: Request) -> dict[str, Any]:
    try:
        return reserve_compile_credit(
            _principal(request),
            reservation_id=body.reservation_id,
            plugin_id=body.plugin_id,
            workflow_id=body.workflow_id,
            session_id=body.session_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _service_error(exc) from exc


@router.post("/usage/compile/commit")
def post_compile_commit(body: ReservationBody, request: Request) -> dict[str, Any]:
    try:
        return commit_compile_credit(_principal(request), body.reservation_id)
    except Exception as exc:  # noqa: BLE001
        raise _service_error(exc) from exc


@router.post("/usage/compile/release")
def post_compile_release(body: ReservationBody, request: Request) -> dict[str, Any]:
    try:
        return release_compile_credit(_principal(request), body.reservation_id)
    except Exception as exc:  # noqa: BLE001
        raise _service_error(exc) from exc
