"""Deterministic text cleanup for DOM + semantic fields."""

from __future__ import annotations

import re


_WS_RE = re.compile(r"\s+")


def collapse_ws(value: str, *, max_len: int) -> str:
    s = _WS_RE.sub(" ", (value or "").strip())
    return s[:max_len]


def normalize_class_token(cls: str) -> str | None:
    c = cls.strip()
    if not c:
        return None
    # Drop obviously dynamic framework tokens (conservative, deterministic heuristics).
    if len(c) > 48:
        return None
    if re.fullmatch(r"[a-z]{1,3}\d{6,}", c):
        return None
    return c
