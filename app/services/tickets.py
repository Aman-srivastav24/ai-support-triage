"""Ticket intake and triage. Knows nothing about HTTP."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.graph.triage import build_triage_graph
from app.models.ticket import Ticket, TicketStatus
from app.models.ticket_citation import TicketCitation
from app.services.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)


def create_ticket(
    db: Session,
    *,
    subject: str,
    body: str,
    customer_email: str,
) -> Ticket:
    """Store an incoming ticket. No processing yet."""
    ticket = Ticket(
        subject=subject,
        body=body,
        customer_email=customer_email,
        status=TicketStatus.RECEIVED,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def process_ticket(db: Session, ticket_id: uuid.UUID) -> Ticket:
    """Run the ticket through the triage graph and persist the outcome.

    The graph decides; this function owns the database. Keeping every write
    here means one transaction to reason about and one place that knows how
    a graph result maps onto a row.
    """
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise ValueError(f"ticket {ticket_id} not found")

    ticket.status = TicketStatus.PROCESSING
    db.commit()

    try:
        graph = build_triage_graph(db)
        result = graph.invoke(
            {
                "ticket_id": ticket.id,
                "subject": ticket.subject,
                "body": ticket.body,
            }
        )

        ticket.category = result["category"]
        ticket.draft_reply = result["draft"]
        ticket.confidence = result["confidence"]
        ticket.escalation_reason = result["escalation_reason"]
        ticket.status = (
            TicketStatus.ESCALATED if result["escalate"] else TicketStatus.DRAFTED
        )

        _store_citations(db, ticket, result["chunks"])

        ticket.processed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(ticket)
        return ticket

    except Exception as exc:
        db.rollback()
        # Re-fetch: after a rollback the object above may be stale or detached.
        ticket = db.get(Ticket, ticket_id)
        if ticket is not None:
            ticket.status = TicketStatus.FAILED
            ticket.escalation_reason = str(exc)[:1000]
            ticket.processed_at = datetime.now(timezone.utc)
            db.commit()
        logger.exception("ticket %s: processing failed", ticket_id)
        raise


def _store_citations(
    db: Session, ticket: Ticket, hits: list[RetrievedChunk]
) -> None:
    """Record which chunks informed the draft, in rank order.

    `used_in_reply` stays false: retrieved is not the same as used. The
    Day 10 reflection node is what can tell the difference.
    """
    for rank, hit in enumerate(hits, start=1):
        db.add(
            TicketCitation(
                ticket_id=ticket.id,
                chunk_id=uuid.UUID(hit.chunk_id),
                rank=rank,
                score=hit.similarity,
            )
        )