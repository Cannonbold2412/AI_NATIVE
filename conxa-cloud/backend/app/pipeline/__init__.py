"""Feature pipeline (Phase 2) — normalize and enrich recorded events."""

from app.pipeline.normalize import passthrough
from app.pipeline.run import PIPELINE_VERSION, run_pipeline

__all__ = ["passthrough", "run_pipeline", "PIPELINE_VERSION"]
