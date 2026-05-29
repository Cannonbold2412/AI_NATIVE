"""Render worker entrypoint.

The current implementation keeps the process alive while Redis-backed queues are
being connected. Long-running operations already have API job wrappers; the next
step is to move those runners behind SKILL_REDIS_URL.
"""

from __future__ import annotations

import logging
import time

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ai-native-worker")


def main() -> None:
    log.info(
        "worker_started queue=%s redis_configured=%s",
        settings.worker_queue_name,
        bool(settings.redis_url),
    )
    while True:
        time.sleep(30)


if __name__ == "__main__":
    main()
