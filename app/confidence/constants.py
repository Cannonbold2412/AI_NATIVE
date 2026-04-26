"""Fixed thresholds from product spec (single source of truth for later phases)."""

from typing import Final

THRESHOLDS: Final[dict[str, float]] = {
    "dom_execute": 0.9,
    "semantic_execute": 0.85,
    "visual_execute": 0.8,
}

# Recovery-only global blend (Layer 4).
RECOVERY_GLOBAL_WEIGHTS: Final[dict[str, float]] = {
    "dom": 0.3,
    "semantic": 0.35,
    "visual": 0.15,
    "context": 0.2,
}
