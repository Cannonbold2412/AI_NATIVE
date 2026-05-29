"""Global pytest configuration for the test suite."""

import os

# Allow tests to run without LLM provider credentials.
os.environ.setdefault("SKILL_ALLOW_NO_PROVIDERS", "1")
# Disable Clerk auth enforcement so route tests don't need valid JWTs.
os.environ.setdefault("SKILL_AUTH_REQUIRED", "false")
