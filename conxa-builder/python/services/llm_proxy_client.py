"""Cloud LLM proxy client used by the local compiler.

Build Studio has no provider keys; it forwards every text/vision LLM call to
the cloud ``/llm/proxy/*`` endpoints with the Clerk JWT. This object exposes the
same ``route_text`` / ``route_vision`` signature as ``app.llm.router.LLMRouter``
so it can be injected wherever the compiler expects a router.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable


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
    ) -> None:
        self._cloud_api = cloud_api.rstrip("/")
        self._token_provider = token_provider
        self._client_header = client_header

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

        try:
            with urllib.request.urlopen(req, timeout=(timeout_ms / 1000) + 5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, dict) else None
        except urllib.error.HTTPError as exc:
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
        except urllib.error.URLError as exc:
            raise CloudUnreachable(
                "No internet connection — compile requires the cloud LLM proxy"
            ) from exc
