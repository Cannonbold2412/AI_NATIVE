"""Input sanitization for IPC command payloads.

The Electron <-> Python bridge is localhost stdin/stdout, but identifiers from
the renderer still flow into filesystem paths (session dirs, plugin folders,
skill-pack slugs). Reject anything that could traverse out of the data dir.
"""

from __future__ import annotations

_FORBIDDEN = ("..", "/", "\\", "\x00")


class InvalidInput(ValueError):
    """Raised when an identifier fails sanitization."""


def safe_identifier(value: object, field: str) -> str:
    """Return ``value`` as a string if it is a safe path component, else raise.

    Safe means: non-empty, no path separators, no ``..``, no NUL byte.
    """
    s = str(value or "").strip()
    if not s:
        raise InvalidInput(f"{field} is required")
    if any(tok in s for tok in _FORBIDDEN):
        raise InvalidInput(f"{field} contains an illegal character")
    return s
