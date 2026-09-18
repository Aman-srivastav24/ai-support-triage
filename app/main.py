from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.api.documents import router as documents_router
from app.api import tickets

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Triages customer support tickets with RAG and human-in-the-loop escalation.",
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(tickets.router)