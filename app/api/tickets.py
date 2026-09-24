"""Public ticket submission endpoints."""

import json
import logging
from collections.abc import Iterator

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.api.deps import DbSession
from app.graph.triage import build_triage_graph
from app.models.ticket import TicketStatus
from app.schemas.ticket import TicketAck, TicketCreate
from app.services.tickets import create_ticket, mark_failed, persist_result, process_ticket

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


def _sse(payload: dict) -> str:
    """Format one SSE event.

    The trailing blank line terminates the event. Without it the client
    buffers indefinitely, waiting for an end that never arrives.
    """
    return f"data: {json.dumps(payload)}\n\n"


def _progress_event(node_name: str, changes: dict) -> dict:
    """Turn a node's output into a client-safe progress event.

    Whitelisted per node. The draft text and chunk contents never leave:
    the streaming endpoint is public, and the same reasoning that keeps
    the draft out of the receipt keeps it out of the stream.
    """
    if node_name == "classify":
        return {"stage": "classified", "category": changes["category"].value}
    if node_name == "retrieve":
        return {"stage": "retrieved", "sources": len(changes["chunks"])}
    if node_name == "draft":
        return {"stage": "drafted"}
    if node_name == "score_confidence":
        return {"stage": "scored", "escalate": changes["escalate"]}
    return {"stage": node_name}


@router.post("/stream")
def submit_ticket_streaming(payload: TicketCreate, db: DbSession) -> StreamingResponse:
    """Submit a ticket and stream triage progress as each node completes.

    Same contract as POST /tickets, delivered live. Progress only — the
    graph's own structure provides the events, so nothing had to be
    instrumented to report them.
    """

    def event_stream() -> Iterator[str]:
        ticket = create_ticket(
            db,
            subject=payload.subject,
            body=payload.body,
            customer_email=payload.customer_email,
        )
        yield _sse({"stage": "received", "id": str(ticket.id)})

        try:
            ticket.status = TicketStatus.PROCESSING
            db.commit()

            graph = build_triage_graph(db)
            result: dict = {}

            for update in graph.stream(
                {
                    "ticket_id": ticket.id,
                    "subject": ticket.subject,
                    "body": ticket.body,
                }
            ):
                # Each update is {node_name: {keys that node returned}}.
                # Accumulate them to rebuild the final state.
                for node_name, changes in update.items():
                    # A node that changed nothing (the terminal nodes) streams
                    # as None rather than an empty dict.
                    if changes:
                        result.update(changes)
                    yield _sse(_progress_event(node_name, changes or {}))

            persist_result(db, ticket, result)
            yield _sse(
                {"stage": "done", "id": str(ticket.id), "status": ticket.status}
            )

        except Exception as exc:
            logger.exception("ticket %s: streaming triage failed", ticket.id)
            mark_failed(db, ticket.id, str(exc))
            yield _sse({"stage": "error", "id": str(ticket.id)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")