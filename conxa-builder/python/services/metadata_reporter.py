"""Report build/publish events to the cloud registry + analytics.

Best-effort: telemetry failures never block a local build. Reuses the Clerk
token so the cloud can attribute events to the org.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable


class MetadataReporter:
    def __init__(self, cloud_api: str, token_provider: Callable[[], str]) -> None:
        self._cloud_api = cloud_api.rstrip("/")
        self._token_provider = token_provider

    def report(self, event: str, data: dict[str, Any]) -> bool:
        """POST a build/publish event. Returns False on any failure (never raises)."""
        url = f"{self._cloud_api}/api/v1/tracking/events"
        body = json.dumps({"event": event, "data": data}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            req.add_header("Authorization", f"Bearer {self._token_provider()}")
        except Exception:
            pass
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status < 400
        except (urllib.error.URLError, OSError):
            return False
