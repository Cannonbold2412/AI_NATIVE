"""FastAPI entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield

from app.api.execution_routes import router as execution_router
from app.api.job_routes import router as job_router
from app.api.plugin_routes import router as plugin_router
from app.api.product_routes import router as product_router
from app.api.razorpay_routes import router as razorpay_router
from app.api.routes import router
from app.api.run_routes import router as run_router
from app.api.security import ProductionRequestMiddleware
from app.api.skill_pack_routes import router as skill_pack_router
from app.api.skillpack_update_routes import router as skillpack_update_router
from app.api.skillpack_update_routes import auth_router as skillpack_auth_router
from app.api.skillpack_update_routes import telemetry_router as skillpack_telemetry_router
from app.api.tracking_routes import public_router as public_tracking_router
from app.api.tracking_routes import router as tracking_router
from app.api.v1_alias_routes import router as v1_alias_router
from app.api.workflow_routes import router as workflow_router
from app.config import settings

app = FastAPI(title="AI Skill Platform", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_preview_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ProductionRequestMiddleware)

app.include_router(router, prefix="/api/v1")
app.include_router(skill_pack_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
app.include_router(job_router, prefix="/api/v1")
app.include_router(product_router, prefix="/api/v1")
app.include_router(v1_alias_router, prefix="/api/v1")
app.include_router(plugin_router, prefix="/api/v1")
app.include_router(run_router, prefix="/api/v1")
app.include_router(execution_router, prefix="/api/v1")
app.include_router(razorpay_router, prefix="/api/v1")
app.include_router(skillpack_update_router, prefix="/api/v1")
app.include_router(skillpack_auth_router, prefix="/api/v1")
app.include_router(skillpack_telemetry_router, prefix="/api/v1")
app.include_router(tracking_router, prefix="/api/v1")
app.include_router(public_tracking_router)  # package-token ingest endpoint for runtimes


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "skill_platform",
        "data_dir": str(settings.data_dir),
    }
