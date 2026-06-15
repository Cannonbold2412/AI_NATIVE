"""Strip lone UTF-16 surrogates that leak in from malformed web DOM text.

Lone surrogates (e.g. U+DC9D) are not encodable as UTF-8 and crash any
write_text(encoding="utf-8") / str.encode("utf-8"). These helpers replace them
with U+FFFD so persisted data stays valid UTF-8.
"""
from __future__ import annotations

import json
from typing import Any


def scrub_text(s: str) -> str:
    return s.encode("utf-8", "surrogatepass").decode("utf-8", "replace")


def scrub_surrogates(obj: Any) -> Any:
    if isinstance(obj, str):
        return scrub_text(obj)
    if isinstance(obj, dict):
        return {k: scrub_surrogates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_surrogates(item) for item in obj]
    return obj


def dumps_safe(obj: Any, **kwargs: Any) -> str:
    """json.dumps guaranteed to produce valid UTF-8 output regardless of input."""
    return scrub_text(json.dumps(obj, **kwargs))
