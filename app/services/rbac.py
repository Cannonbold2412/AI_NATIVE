from __future__ import annotations

from fastapi import HTTPException

from app.services.saas import Principal


def require_admin(principal: Principal) -> None:
    if principal.role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="admin role required")
