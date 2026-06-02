"""Plain `/api/v1` resource aliases for the production API contract.

Recording and skill-package aliases were removed when those flows moved into the
local Build Studio. Audit events are served by audit_routes.py.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["v1-aliases"])
