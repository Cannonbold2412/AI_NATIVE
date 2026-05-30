"""Global pytest configuration for the test suite."""

import os

# Allow tests to run without LLM provider credentials.
os.environ.setdefault("SKILL_ALLOW_NO_PROVIDERS", "1")
# Disable Clerk auth enforcement so route tests don't need valid JWTs.
os.environ.setdefault("SKILL_AUTH_REQUIRED", "false")

# Install the concrete provider-pool router into the conxa_core singleton so the
# compile pipeline behaves exactly as it did pre-split (when get_router() lazily
# built an LLMRouter). At runtime the Build Studio installs the metered cloud
# proxy client instead via conxa_core.llm.set_router().
import conxa_core.llm as _core_llm  # noqa: E402

try:
    from app.llm.router import LLMRouter  # noqa: E402

    _core_llm.set_router(LLMRouter())
except Exception:  # pragma: no cover - router optional for non-compile tests
    pass
