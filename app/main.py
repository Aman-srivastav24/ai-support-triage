from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Triages customer support tickets with RAG and human-in-the-loop escalation.",
)

app.include_router(health_router)