"""FastAPI entrypoint for the thin Conxa cloud SaaS.

The cloud serves the metered LLM proxy, auth, billing, dashboard, plugin/installer
hosting, runtime sync/update manifests, and telemetry. Recording, compiling, and
building all happen locally in the Build Studio.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from conxa_core.config import settings
from conxa_core.db import healthcheck, init_db, using_database

from app.api.entitlement_routes import router as entitlement_router
from app.api.job_routes import router as job_router
from app.api.llm_proxy_routes import router as llm_proxy_router
from app.api.plugin_routes import router as plugin_router
from app.api.product_routes import router as product_router
from app.api.publish_routes import installers_router, router as publish_router
from app.api.razorpay_routes import router as razorpay_router
from app.api.run_routes import router as run_router
from app.api.security import ProductionRequestMiddleware
from app.api.skillpack_update_routes import router as skillpack_update_router
from app.api.skillpack_update_routes import telemetry_router as skillpack_telemetry_router
from app.api.tracking_routes import public_router as public_tracking_router
from app.api.tracking_routes import router as tracking_router
from app.api.updates_routes import router as updates_router
from app.api.v1_alias_routes import router as v1_alias_router


def _validate_production_config() -> None:
    """Fail fast in production rather than booting a half-configured service.

    When ``SKILL_AUTH_REQUIRED`` is true we are running as the public cloud and
    must have a real database, Clerk auth, explicit CORS origins, and Razorpay
    billing configured. (Provider keys are enforced separately by the Settings
    validator.) The filesystem DB fallback must never silently activate here.
    """
    if not settings.auth_required:
        return
    missing: list[str] = []
    if not settings.database_url:
        missing.append("SKILL_DATABASE_URL (filesystem fallback is not allowed in production)")
    if not settings.clerk_issuer:
        missing.append("SKILL_CLERK_ISSUER")
    if not settings.clerk_jwks_url:
        missing.append("SKILL_CLERK_JWKS_URL")
    if not settings.cors_origins:
        missing.append("SKILL_CORS_ORIGINS")
    if not (settings.razorpay_key_id and settings.razorpay_key_secret and settings.razorpay_webhook_secret):
        missing.append("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET / RAZORPAY_WEBHOOK_SECRET")
    if not (settings.razorpay_starter_plan_id and settings.razorpay_pro_plan_id):
        missing.append("RAZORPAY_STARTER_PLAN_ID / RAZORPAY_PRO_PLAN_ID")
    if missing:
        raise RuntimeError(
            "Refusing to start: SKILL_AUTH_REQUIRED=true but these are unset: "
            + ", ".join(missing)
        )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _validate_production_config()
    init_db()
    yield


app = FastAPI(title="Conxa Cloud", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_preview_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ProductionRequestMiddleware)

app.include_router(job_router, prefix="/api/v1")
app.include_router(entitlement_router, prefix="/api/v1")
app.include_router(product_router, prefix="/api/v1")
app.include_router(v1_alias_router, prefix="/api/v1")
app.include_router(plugin_router, prefix="/api/v1")
app.include_router(llm_proxy_router, prefix="/api/v1")
app.include_router(publish_router, prefix="/api/v1")
app.include_router(installers_router, prefix="/api/v1")
app.include_router(run_router, prefix="/api/v1")
app.include_router(razorpay_router, prefix="/api/v1")
app.include_router(skillpack_update_router, prefix="/api/v1")
app.include_router(skillpack_telemetry_router, prefix="/api/v1")
app.include_router(tracking_router, prefix="/api/v1")
app.include_router(public_tracking_router)  # package-token ingest endpoint for runtimes
app.include_router(updates_router, prefix="/api/v1")


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "conxa_cloud"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. Does not touch dependencies."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> JSONResponse:
    """Readiness: dependencies (DB) are reachable; used to gate deploys."""
    try:
        healthcheck()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "database": "down", "error": str(exc)[:200]},
        )
    return JSONResponse(content={"status": "ready", "database": "up" if using_database() else "filesystem"})
