"""Shared state for the triage graph.

One object travels through every node. Each node reads what it needs and
returns only the keys it changed; LangGraph merges those into the state.

Inputs are set when the graph is invoked. Outputs are filled in by nodes
as they run, which is why every key is optional.
"""

import uuid
from typing import TypedDict

from app.schemas.classification import TicketCategory
from app.services.retrieval import RetrievedChunk


class TriageState(TypedDict, total=False):
    """State passed between triage graph nodes."""

    # --- inputs, set when the graph is invoked ---
    ticket_id: uuid.UUID
    subject: str
    body: str

    # --- written by nodes ---
    category: TicketCategory          # classify
    chunks: list[RetrievedChunk]      # retrieve (already filtered by the floor)
    draft: str                        # draft
    confidence: float                 # score_confidence
    escalate: bool                    # score_confidence — drives the branch
    escalation_reason: str | None     # score_confidence, set only when escalating