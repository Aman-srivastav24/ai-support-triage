"""Request and response shapes for the public ticket endpoint."""

import uuid

from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    """What a customer submits. Public endpoint — assume hostile input."""

    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=5000)
    customer_email: str = Field(max_length=320)


class CitationRead(BaseModel):
    """One chunk that informed the draft answer."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    similarity: float


class TicketRead(BaseModel):
    """What the caller gets back."""

    id: uuid.UUID
    status: str
    draft_reply: str | None
    citations: list[CitationRead]