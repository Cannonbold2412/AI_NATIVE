"""Cloud LLM proxy client used by the local compiler.

Build Studio has no provider keys; it forwards every text/vision LLM call to
the cloud ``/llm/proxy/*`` endpoints with the Clerk JWT. This object exposes the
same ``route_text`` / ``route_vision`` signature as ``app.llm.router.LLMRouter``
so it can be injected wherever the compiler expects a router.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable

# Minimum HTTP timeout for proxied calls (double-hop: Studio → cloud → LLM provider).
# The per-task timeout_ms (e.g. llm_text_timeout_ms=2000) was designed for direct
# LLM endpoints; proxied calls need a much larger budget.
_PROXY_MIN_TIMEOUT_S = 90.0


class QuotaExceeded(RuntimeError):
    """The org hit its monthly LLM token quota (HTTP 429)."""


class CloudUnreachable(RuntimeError):
    """The proxy could not be reached (network error / no internet)."""


class LLMProxyClient:
    def __init__(
        self,
        cloud_api: str,
        token_provider: Callable[[], str],
        *,
        client_header: str = "build-studio",
        on_api_call: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._cloud_api = cloud_api.rstrip("/")
        self._token_provider = token_provider
        self._client_header = client_header
        self._on_api_call = on_api_call

    # -- public interface mirroring LLMRouter --------------------------------

    def route_text(
        self,
        task: str,
        payload: dict[str, Any],
        timeout_ms: int,
        *,
        error_detail: list[str] | None = None,
    ) -> dict[str, Any] | None:
        return self._post("text", task, payload, timeout_ms, error_detail=error_detail)

    def route_vision(
        self,
        task: str,
        payload: dict[str, Any],
        timeout_ms: int,
        *,
        error_detail: list[str] | None = None,
    ) -> dict[str, Any] | None:
        return self._post("vision", task, payload, timeout_ms, error_detail=error_detail)

    # -- internals -----------------------------------------------------------

    def _post(
        self,
        kind: str,
        task: str,
        payload: dict[str, Any],
        timeout_ms: int,
        *,
        error_detail: list[str] | None,
        _retried: bool = False,
    ) -> dict[str, Any] | None:
        url = f"{self._cloud_api}/api/v1/llm/proxy/{kind}"
        body = json.dumps(
            {"task": task, "payload": payload, "timeout_ms": int(timeout_ms)}
        ).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Conxa-Client", self._client_header)
        req.add_header("Authorization", f"Bearer {self._token_provider()}")

        # Use a minimum 90s budget for proxied calls; the caller's timeout_ms is
        # calibrated for direct LLM endpoints, not a double-hop proxy.
        http_timeout_s = max(timeout_ms / 1000, _PROXY_MIN_TIMEOUT_S) + 5.0
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=http_timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            duration_ms = int((time.monotonic() - t0) * 1000)
            if self._on_api_call is not None:
                self._on_api_call({"task": task, "kind": kind, "duration_ms": duration_ms, "status": "ok"})
            return data if isinstance(data, dict) else None
        except urllib.error.HTTPError as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            if self._on_api_call is not None:
                self._on_api_call({"task": task, "kind": kind, "duration_ms": duration_ms, "status": f"http_{exc.code}"})
            if exc.code == 401 and not _retried:
                # Token likely expired — let the auth layer refresh, then retry once.
                return self._post(
                    kind, task, payload, timeout_ms,
                    error_detail=error_detail, _retried=True,
                )
            if exc.code == 429:
                raise QuotaExceeded("Monthly LLM quota reached") from exc
            if error_detail is not None:
                error_detail.append(f"proxy HTTP {exc.code}")
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # urllib wraps connect/header timeouts in URLError; Windows raises the
            # body-read timeout as a raw TimeoutError/OSError ("The read operation
            # timed out"). Both cases mean the proxy is unreachable or too slow.
            duration_ms = int((time.monotonic() - t0) * 1000)
            if self._on_api_call is not None:
                self._on_api_call({"task": task, "kind": kind, "duration_ms": duration_ms, "status": "error"})
            raise CloudUnreachable(
                f"Cloud LLM proxy unreachable or timed out ({exc})"
            ) from exc
