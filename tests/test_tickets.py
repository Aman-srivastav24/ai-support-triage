"""Ticket triage end to end, through the public endpoint.

One test for the drafted path, one per escalation rule. Each escalation test
makes exactly one rule true, so a failure names the rule that broke. Every
test also asserts the fake LLM was actually called: classify_ticket returns
OTHER on failure, and OTHER escalates, so without that check a missing
override would still produce an 'escalated' ticket and a passing test.
"""

import uuid

from sqlalchemy import text

from app.db.session import engine
from app.graph.nodes import REFUSAL_SENTENCE
from app.schemas.classification import TicketCategory

DOC_TEXT = (
    "Refunds are available within 14 days of the first charge on a new "
    "subscription. Renewal charges are not refundable."
)

# Shares most of its words with DOC_TEXT, so the fake embedder scores it
# well above the similarity floor (see test_fake_embedder.py).
ANSWERABLE = {
    "subject": "Refunds",
    "body": "Are refunds available within 14 days of the first charge?",
    "customer_email": "customer@example.com",
}

UNRELATED = {
    "subject": "Football",
    "body": "Who won the football match last night?",
    "customer_email": "customer@example.com",
}


def add_document(client, admin_headers) -> None:
    response = client.post(
        "/documents",
        headers=admin_headers,
        files={"file": ("refunds.txt", DOC_TEXT.encode("utf-8"), "text/plain")},
        data={"title": "Refund policy"},
    )
    assert response.status_code == 202, response.text


def submit(client, ticket: dict) -> dict:
    response = client.post("/tickets", json=ticket)
    assert response.status_code == 201, response.text
    return response.json()


def stored(ticket_id: str):
    """Read what triage persisted. The public receipt deliberately hides it."""
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT t.status, t.category, t.draft_reply, t.escalation_reason, "
                "  (SELECT count(*) FROM ticket_citations c WHERE c.ticket_id = t.id) "
                "  AS citations "
                "FROM tickets t WHERE t.id = :id"
            ),
            {"id": uuid.UUID(ticket_id)},
        ).mappings().one()


def test_answerable_ticket_is_drafted_from_the_uploaded_document(
    client, admin_headers, fake_llm
):
    add_document(client, admin_headers)

    receipt = submit(client, ANSWERABLE)

    # The public receipt says what happened and nothing more.
    assert set(receipt) == {"id", "status"}
    assert receipt["status"] == "drafted"

    # The fake was used, once each, and retrieval handed it the document.
    assert len(fake_llm.classify_calls) == 1
    assert len(fake_llm.draft_calls) == 1
    _, context_chunks = fake_llm.draft_calls[0]
    assert any("14 days" in chunk for chunk in context_chunks)

    row = stored(receipt["id"])
    assert row["category"] == "billing"
    assert row["draft_reply"] == fake_llm.reply
    assert row["escalation_reason"] is None
    assert row["citations"] >= 1


def test_a_refusal_from_the_model_escalates(client, admin_headers, fake_llm):
    add_document(client, admin_headers)
    fake_llm.reply = REFUSAL_SENTENCE

    receipt = submit(client, ANSWERABLE)

    assert receipt["status"] == "escalated"
    assert len(fake_llm.draft_calls) == 1
    assert (
        stored(receipt["id"])["escalation_reason"]
        == "model could not answer from the retrieved context"
    )


def test_an_other_category_escalates_even_with_a_good_draft(
    client, admin_headers, fake_llm
):
    add_document(client, admin_headers)
    fake_llm.category = TicketCategory.OTHER

    receipt = submit(client, ANSWERABLE)

    assert receipt["status"] == "escalated"
    assert len(fake_llm.classify_calls) == 1
    assert (
        stored(receipt["id"])["escalation_reason"]
        == "ticket does not fit a documented category"
    )


def test_no_relevant_chunks_escalates_without_asking_the_model_to_draft(
    client, fake_llm
):
    # No documents uploaded: retrieval finds nothing to clear the floor.
    receipt = submit(client, UNRELATED)

    assert receipt["status"] == "escalated"
    assert len(fake_llm.classify_calls) == 1
    # The draft node writes the refusal itself rather than paying for an
    # API call with no context, so the model is never asked to draft.
    assert fake_llm.draft_calls == []
    assert "no chunks above the similarity floor" in stored(receipt["id"])["escalation_reason"]