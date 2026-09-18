"""Ticket intake and draft generation. Knows nothing about HTTP."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.ticket import Ticket, TicketStatus
from app.models.ticket_citation import TicketCitation
from app.services.llm import draft_answer
from app.services.retrieval import RetrievedChunk, search_chunks

logger = logging.getLogger(__name__)

SIMILARITY_FLOOR = 0.55
TOP_K = 3


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
    """Retrieve context, draft a reply, and store citations."""
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise ValueError(f"ticket {ticket_id} not found")

    ticket.status = TicketStatus.PROCESSING
    db.commit()

    try:
        query = f"{ticket.subject}\n{ticket.body}" if ticket.subject else ticket.body
        hits = search_chunks(db, query, top_k=TOP_K)
        usable = [hit for hit in hits if hit.similarity >= SIMILARITY_FLOOR]

        if not usable:
            ticket.draft_reply = None
            ticket.status = TicketStatus.DRAFTED
            ticket.escalation_reason = (
                f"no chunk above similarity floor {SIMILARITY_FLOOR}"
            )
            logger.info("ticket %s: nothing above floor, no draft", ticket_id)
        else:
            ticket.draft_reply = draft_answer(query, [hit.content for hit in usable])
            ticket.status = TicketStatus.DRAFTED
            _store_citations(db, ticket, usable)

        ticket.processed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(ticket)
        return ticket

    except Exception as exc:
        db.rollback()
        ticket.status = TicketStatus.FAILED
        ticket.escalation_reason = str(exc)[:1000]
        ticket.processed_at = datetime.now(timezone.utc)
        db.commit()
        logger.exception("ticket %s: processing failed", ticket_id)
        raise


def _store_citations(
    db: Session, ticket: Ticket, hits: list[RetrievedChunk]
) -> None:
    """Record which chunks informed the draft, in rank order."""
    for rank, hit in enumerate(hits, start=1):
        db.add(
            TicketCitation(
                ticket_id=ticket.id,
                chunk_id=uuid.UUID(hit.chunk_id),
                rank=rank,
                score=hit.similarity,
            )
        )