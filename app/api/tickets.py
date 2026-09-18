"""Public ticket submission endpoint."""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.schemas.ticket import CitationRead, TicketCreate, TicketRead
from app.services.llm import LLMError
from app.services.tickets import create_ticket, process_ticket

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
def submit_ticket(payload: TicketCreate, db: DbSession) -> TicketRead:
    """Accept a customer ticket, draft a grounded reply, return it with citations.

    Public: no authentication. Rate limiting is Day 12.
    """
    ticket = create_ticket(
        db,
        subject=payload.subject,
        body=payload.body,
        customer_email=payload.customer_email,
    )

    try:
        ticket = process_ticket(db, ticket.id)
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Ticket received but the draft could not be generated.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ticket received but processing failed.",
        ) from exc

    return TicketRead(
        id=ticket.id,
        status=ticket.status,
        draft_reply=ticket.draft_reply,
        citations=[
            CitationRead(
                chunk_id=c.chunk_id,
                document_id=c.chunk.document_id,
                document_title=c.chunk.document.title,
                similarity=c.score,
            )
            for c in ticket.citations
        ],
    )