"""FastAPI entrypoint — mounts recorder + future compiler/update-step routes."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.job_routes import router as job_router
from app.api.product_routes import router as product_router
from app.api.routes import router
from app.api.security import ProductionRequestMiddleware
from app.api.skill_pack_routes import router as skill_pack_router
from app.api.v1_alias_routes import router as v1_alias_router
from app.api.workflow_routes import router as workflow_router
from app.config import settings

app = FastAPI(title="AI Skill Platform", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_preview_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ProductionRequestMiddleware)

# Legacy local endpoints remain available during the migration.
app.include_router(router)
app.include_router(skill_pack_router)
app.include_router(workflow_router)

# Production API surface. Existing resources are mounted under /api/v1 and
# additional plain aliases expose /recordings, /packages, /jobs, and /audit-events.
app.include_router(router, prefix="/api/v1")
app.include_router(skill_pack_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
app.include_router(job_router, prefix="/api/v1")
app.include_router(product_router, prefix="/api/v1")
app.include_router(v1_alias_router, prefix="/api/v1")


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "skill_platform",
        "data_dir": str(settings.data_dir),
    }
