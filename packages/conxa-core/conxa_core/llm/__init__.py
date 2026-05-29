"""LLM router singleton + protocol for the compile pipeline.

The compile pipeline (recorder/compiler/selector generators, in the Build
Studio) calls ``get_router().route_text(...)`` / ``route_vision(...)`` without
knowing where the call ultimately goes. The Build Studio installs a metered
cloud-proxy client via :func:`set_router`; the cloud itself does not use this
singleton — it talks to its concrete provider pool (``app/llm/router.py``)
directly inside the proxy endpoint.

Imports of :func:`get_router` in the pipeline are intentionally lazy (inside
functions) so the router can be configured at startup before the first call.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RouterProtocol(Protocol):
    def route_text(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None: ...

    def route_vision(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None: ...


_router: RouterProtocol | None = None


def set_router(router: RouterProtocol | None) -> None:
    """Install the router used by the compile pipeline (e.g. the cloud proxy client)."""
    global _router
    _router = router


def get_router() -> RouterProtocol:
    if _router is None:
        raise RuntimeError(
            "LLM router is not configured. Call conxa_core.llm.set_router() "
            "(the Build Studio installs the metered cloud-proxy client at startup)."
        )
    return _router
