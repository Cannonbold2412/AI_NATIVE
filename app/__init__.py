"""AI Skill Platform — recorder, compiler, and skill package APIs (MVP)."""

import asyncio
import sys

# Must run as early as possible for Windows subprocess support (Playwright).
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
