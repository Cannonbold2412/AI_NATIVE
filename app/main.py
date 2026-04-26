"""FastAPI entrypoint — mounts recorder + future compiler/update-step routes."""

import asyncio
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.workflow_routes import router as workflow_router
from app.config import settings

# Playwright on Windows requires subprocess-capable event loop policy.
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(title="AI Skill Platform", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(workflow_router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "skill_platform",
        "data_dir": str(settings.data_dir),
    }
