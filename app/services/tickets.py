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


def persist_result(db: Session, ticket: Ticket, result: dict) -> Ticket:
    """Map a completed graph result onto the ticket row and commit.

    The single place that knows how graph output becomes a row. Both the
    blocking endpoint and the streaming one call this, so the two paths
    cannot drift apart in what they store.
    """
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


def mark_failed(db: Session, ticket_id: uuid.UUID, reason: str) -> None:
    """Record that triage failed for this ticket.

    Re-fetches after rollback: the caller's object may be stale or detached
    by the time this runs, and writing to a detached instance is unreliable.
    """
    db.rollback()
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        return
    ticket.status = TicketStatus.FAILED
    ticket.escalation_reason = reason[:1000]
    ticket.processed_at = datetime.now(timezone.utc)
    db.commit()


def process_ticket(db: Session, ticket_id: uuid.UUID) -> Ticket:
    """Run the ticket through the triage graph and persist the outcome.

    The graph decides; this function owns the database.
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
        return persist_result(db, ticket, result)

    except Exception as exc:
        mark_failed(db, ticket_id, str(exc))
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