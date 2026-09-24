"""Nodes for the triage graph.

Each node takes the full state and returns only the keys it changed.
Nodes contain no business logic: they call services that already exist
and shape the result into state. The graph decides order; services do work.
"""

import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.graph.state import TriageState
from app.schemas.classification import TicketCategory
from app.services.cache import get_json, make_key, set_json
from app.services.llm import classify_ticket, draft_answer
from app.services.retrieval import search_chunks

logger = logging.getLogger(__name__)

# The exact sentence the grounded prompt instructs the model to return when
# the context cannot answer the question. Matching on it is how the system
# detects "the model told us it had nothing to work with".
REFUSAL_SENTENCE = "The documentation does not cover this."

# Below this, a chunk is treated as junk. Set on Day 3, just above the
# observed ceiling for unrelated questions (0.525). It separates rubbish
# from on-topic; it does NOT separate answerable from unanswerable.
SIMILARITY_FLOOR = 0.55

TOP_K = 3

# Drafts depend on the corpus, which changes when an admin uploads a
# document. Five minutes is a starting point, not a derived value — it
# would be tuned against how often the documents actually change.
DRAFT_CACHE_TTL_SECONDS = 300


def _build_query(state: TriageState) -> str:
    """Combine subject and body for search and drafting.

    The subject often carries the most searchable terms — an error code, a
    product name — so dropping it loses signal.
    """
    subject = state.get("subject") or ""
    return f"{subject}\n{state['body']}" if subject else state["body"]


def classify(state: TriageState) -> dict:
    """Decide what kind of ticket this is."""
    category = classify_ticket(state["subject"], state["body"])
    logger.info("ticket %s classified as %s", state["ticket_id"], category.value)
    return {"category": category}


def make_retrieve_node(db: Session):
    """Build the retrieve node, bound to this request's database session.

    The session is closed over rather than carried in state: it belongs to
    the request, not to the graph.
    """

    def retrieve(state: TriageState) -> dict:
        results = search_chunks(db, _build_query(state), top_k=TOP_K)
        kept = [c for c in results if c.similarity >= SIMILARITY_FLOOR]
        logger.info(
            "ticket %s retrieved %d chunks, %d above floor",
            state["ticket_id"],
            len(results),
            len(kept),
        )
        return {"chunks": kept}

    return retrieve


def draft(state: TriageState) -> dict:
    """Draft a grounded reply from the retrieved chunks.

    Cached on the question AND the chunk IDs, because unlike classification
    this output depends on the corpus, not just the input. A short TTL backs
    that up: keying on chunk IDs catches a different retrieval, but not an
    edit to a document that keeps the same chunks.
    """
    chunks = state["chunks"]

    if not chunks:
        # Nothing cleared the floor. Calling the model with no context would
        # spend an API call to produce the refusal sentence we can write here.
        return {"draft": REFUSAL_SENTENCE}

    query = _build_query(state)
    settings = get_settings()

    # Chunk IDs are part of the key: the same question over different
    # retrieved context is a different question. Sorted so the fingerprint
    # is stable for the same set of chunks regardless of retrieval order.
    chunk_fingerprint = ",".join(sorted(c.chunk_id for c in chunks))
    cache_key = make_key("draft", settings.groq_model, f"{query}||{chunk_fingerprint}")

    cached = get_json(cache_key)
    if cached is not None:
        logger.info("draft cache hit")
        return {"draft": cached}

    answer = draft_answer(query, [c.content for c in chunks])
    set_json(cache_key, answer, ttl_seconds=DRAFT_CACHE_TTL_SECONDS)
    return {"draft": answer}


def score_confidence(state: TriageState) -> dict:
    """Decide whether this draft can go back as a suggestion.

    Rule-based and deterministic. Every input is something an earlier node
    observed — no extra model call, and no self-rated confidence, which is
    unreliable precisely when the model is fluently wrong.

    Catches the ABSENCE of grounding. Does not catch bad reasoning over good
    grounding (see the Day 3 'signed up last week' case) — that needs the
    Day 10 reflection node and the human reviewer.
    """
    chunks = state["chunks"]
    top_score = max((c.similarity for c in chunks), default=0.0)

    reasons: list[str] = []
    if not chunks:
        reasons.append("no chunks above the similarity floor")
    if REFUSAL_SENTENCE in state["draft"]:
        reasons.append("model could not answer from the retrieved context")
    if state["category"] is TicketCategory.OTHER:
        reasons.append("ticket does not fit a documented category")

    escalate = bool(reasons)
    reason = "; ".join(reasons) if escalate else None

    logger.info(
        "ticket %s confidence=%.4f escalate=%s reason=%s",
        state["ticket_id"],
        top_score,
        escalate,
        reason,
    )
    return {
        "confidence": top_score,
        "escalate": escalate,
        "escalation_reason": reason,
    }