"""Application entry point: logging, routers, and the frontend."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.tickets import router as tickets_router
from app.core.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)

settings = get_settings()

# Found relative to this file, not the working directory, so it resolves the
# same way under uvicorn, pytest, and inside the container.
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Triages customer support tickets with RAG and human-in-the-loop escalation.",
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(tickets_router)

# Mounted LAST. A mount at "/" matches every path, and routes are checked in
# the order they were added, so the API routers above must come first or the
# frontend would shadow them.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")