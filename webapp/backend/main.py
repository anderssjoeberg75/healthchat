"""HealthChat web application entry point.

Run locally with:

    uvicorn webapp.backend.main:app --reload

The API lives under ``/api``; everything else serves the single-page frontend.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, config
from .routers import auth_routes, chat_routes, data_routes, oauth_routes, settings_routes, sync_routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)



def _bootstrap() -> None:
    """Create the account tables and data directories (idempotent)."""
    auth.init_db()
    config.USER_DATA_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _bootstrap()
    logger.info("HealthChat %s ready — data dir: %s", config.APP_VERSION, config.DATA_DIR)
    yield


app = FastAPI(
    title="HealthChat",
    version=config.APP_VERSION,
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# Also run at import time so the schema exists even when the app is mounted or
# imported by a test client without the lifespan hook.
_bootstrap()

app.include_router(auth_routes.router)
app.include_router(settings_routes.router)
app.include_router(data_routes.router)
app.include_router(sync_routes.router)
app.include_router(chat_routes.router)
app.include_router(oauth_routes.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": config.APP_VERSION}


@app.exception_handler(404)
async def spa_fallback(request: Request, exc):
    """Unknown non-API paths fall back to the single-page app."""
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return FileResponse(config.FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
