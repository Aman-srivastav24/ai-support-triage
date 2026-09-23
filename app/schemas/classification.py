"""Structured output schema for ticket classification."""

from enum import StrEnum

from pydantic import BaseModel, Field


class TicketCategory(StrEnum):
    """What kind of ticket this is.

    Mirrors the document types in the corpus so the value can later
    filter retrieval. OTHER exists because structured output cannot
    refuse — without an escape value the model is forced to mislabel
    an off-topic ticket as one of the real categories.
    """

    BILLING = "billing"
    TECHNICAL = "technical"
    ACCOUNT = "account"
    OTHER = "other"


class TicketClassification(BaseModel):
    """What the LLM must return when classifying a ticket.

    Sent to the model as a JSON schema and used to validate the reply.
    One definition, both ends.
    """

    category: TicketCategory = Field(
        description="The single category that best fits the ticket."
    )