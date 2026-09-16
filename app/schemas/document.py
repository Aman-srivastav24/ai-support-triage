"""Pydantic schemas for the document endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.document import DocumentStatus


class DocumentRead(BaseModel):
    """A document as returned by the API. Never includes raw_text."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_filename: str | None
    status: DocumentStatus
    chunk_count: int
    error_message: str | None
    created_at: datetime
    uploaded_by_id: uuid.UUID