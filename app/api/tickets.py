"""Public ticket submission endpoint."""

import logging

from fastapi import APIRouter, status

from app.api.deps import DbSession
from app.schemas.ticket import TicketAck, TicketCreate

from app.services.tickets import create_ticket, process_ticket

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("", response_model=TicketAck, status_code=status.HTTP_201_CREATED)
def submit_ticket(payload: TicketCreate, db: DbSession) -> TicketAck:
    """Accept a customer ticket and triage it.

    Public: no authentication. Rate limiting is Day 12.

    Returns a receipt only. The draft is written for a support agent to
    review and is fetched from the agent-facing endpoint, not returned
    here — an unreviewed draft in the customer's hands is not a draft.

    Triage failure is not reported to the caller: the ticket was stored
    and a human will see it either way. Telling the customer it failed
    invites a resubmission of a ticket that already exists.
    """
    ticket = create_ticket(
        db,
        subject=payload.subject,
        body=payload.body,
        customer_email=payload.customer_email,
    )

    try:
        ticket = process_ticket(db, ticket.id)
    except Exception:
        # process_ticket has already marked the ticket FAILED and logged
        # the traceback. The receipt below is still accurate.
        logger.warning("ticket %s: triage failed, acknowledging anyway", ticket.id)

    return TicketAck(id=ticket.id, status=ticket.status)