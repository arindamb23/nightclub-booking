# AI Hunters ComfyFlow v1.0.14
"""FastAPI application for AI Hunters ComfyFlow."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import APP_NAME, APP_VERSION
from app.config import get_settings
from app.events import bus
from app.routers import system, models, workflows, runs, templates, nodepacks
from app.services.registry import registry
from app.services import workflows as workflows_service


def _migrate_parallel_downloads(settings) -> None:
    """v1.0.6: models download one at a time by default. Moves the old default (2) to 1 once."""
    marker = settings.data_dir / ".downloads_one_by_one"
    if marker.exists():
        return
    try:
        from app.config import ENV_PATH, update_env, reload_settings

        text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
        if any(line.strip().replace(" ", "") == "MAX_PARALLEL_DOWNLOADS=2" for line in text.splitlines()):
            update_env({"MAX_PARALLEL_DOWNLOADS": "1"})
            reload_settings()
        marker.write_text("1", encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - never block start-up
        print(f"Download setting not migrated: {e}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    bus.bind(asyncio.get_running_loop())
    settings = get_settings()
    for sub in ("workflows", "runs", "outputs", "uploads"):
        (settings.data_dir / sub).mkdir(parents=True, exist_ok=True)
    registry.load()
    _migrate_parallel_downloads(settings)
    try:
        migrated = workflows_service.migrate_group_nodes()
        if migrated:
            print(f"Re-converted workflows with group nodes / subgraphs: {', '.join(migrated)}")
    except Exception as e:  # noqa: BLE001
        print(f"Group node migration skipped: {e}")
    try:
        workflows_service.seed_samples()
    except Exception as e:  # noqa: BLE001 - samples are optional
        print(f"Sample workflows could not be added: {e}")
    yield


settings = get_settings()
app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://localhost:{settings.frontend_port}", f"http://127.0.0.1:{settings.frontend_port}"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": f"Unexpected server error: {type(exc).__name__}: {exc}"})


@app.get("/api/health")
def health():
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}


for r in (system.router, models.router, workflows.router, workflows.samples_router, templates.router, runs.router, nodepacks.router):
    app.include_router(r)
