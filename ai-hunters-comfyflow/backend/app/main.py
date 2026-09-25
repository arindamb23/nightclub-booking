# AI Hunters ComfyFlow v1.0.1
"""FastAPI application for AI Hunters ComfyFlow."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import APP_NAME, APP_VERSION
from app.config import get_settings
from app.events import bus
from app.routers import system, models, workflows, runs
from app.services.registry import registry


@asynccontextmanager
async def lifespan(_: FastAPI):
    bus.bind(asyncio.get_running_loop())
    settings = get_settings()
    for sub in ("workflows", "runs", "outputs", "uploads"):
        (settings.data_dir / sub).mkdir(parents=True, exist_ok=True)
    registry.load()
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


for r in (system.router, models.router, workflows.router, runs.router):
    app.include_router(r)
