"""Request and response shapes for ticket endpoints."""

import uuid
from datetime import datetime  # ← CHANGE

from pydantic import BaseModel, Field


class TicketCreate(BaseModel):
    """What a customer submits. Public endpoint — assume hostile input."""

    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=5000)
    customer_email: str = Field(max_length=320)


class TicketAck(BaseModel):
    """What the PUBLIC endpoint returns: a receipt, nothing more.

    The draft is written for a support agent to review, so it must not
    reach the customer — a draft the customer has already read is not a
    draft. Citations, scores and categories are internal: exposing them
    would let an anonymous caller map the corpus by probing with crafted
    questions and reading the similarity back.
    """

    id: uuid.UUID
    status: str


class CitationRead(BaseModel):
    """One chunk that informed the draft answer."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    similarity: float


class TicketRead(BaseModel):
    """Full triage result. AGENT-FACING — never returned to a public caller.

    Includes the original question and the customer's address: an agent
    cannot review a draft without seeing what was asked, or reply without
    knowing who asked. That makes this personal data, which is why the
    endpoint serving it requires authentication.
    """

    id: uuid.UUID
    status: str
    subject: str | None  # ← CHANGE
    body: str  # ← CHANGE
    customer_email: str  # ← CHANGE
    created_at: datetime  # ← CHANGE
    category: str | None
    draft_reply: str | None
    confidence: float | None
    escalation_reason: str | None
    citations: list[CitationRead]