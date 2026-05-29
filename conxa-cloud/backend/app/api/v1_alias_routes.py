"""Plain `/api/v1` resource aliases for the production API contract.

Recording and skill-package aliases were removed when those flows moved into the
local Build Studio; only the dashboard audit-events alias remains.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["v1-aliases"])


@router.get("/audit-events")
def list_audit_events() -> dict[str, Any]:
    return {"audit_events": []}
