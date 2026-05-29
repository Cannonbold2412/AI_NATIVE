"""Feature pipeline (Phase 2) — normalize and enrich recorded events."""

from conxa_compile.pipeline.normalize import passthrough
from conxa_compile.pipeline.run import PIPELINE_VERSION, run_pipeline

__all__ = ["passthrough", "run_pipeline", "PIPELINE_VERSION"]
