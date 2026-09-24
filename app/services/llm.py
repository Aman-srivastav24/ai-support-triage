"""Answer generation and ticket classification via the Groq API."""

import logging

import httpx

from app.core.config import get_settings
from app.schemas.classification import TicketCategory, TicketClassification
from app.services.cache import get_json, make_key, set_json

logger = logging.getLogger(__name__)

_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMError(Exception):
    """Raised when the language model provider fails or returns nothing usable."""


# GROUNDED PROMPT. The naive version (no context restriction) produced a
# fabricated support process on Day 3 — see PROGRESS_LOG.md.
_SYSTEM_PROMPT = """You are a support assistant drafting a reply for a human agent to review.

Rules:
- Answer ONLY using the context provided. The context is the complete set of information available to you.
- If the context does not contain the answer, say exactly: "The documentation does not cover this." Then stop. Do not suggest workarounds, next steps, or who to contact unless that information appears in the context.
- Never invent email addresses, phone numbers, prices, timeframes, processes, or policies.
- Do not use knowledge from your training. If it is not in the context, you do not know it.
- If the context partially answers the question, state what it does cover and say plainly which part is not covered.
- Be brief and factual. Do not add closing pleasantries."""


_CLASSIFY_PROMPT = """You categorise customer support tickets.

Read the ticket and choose the single category that best fits:
- billing: payments, charges, refunds, invoices, pricing, subscriptions
- technical: errors, crashes, something not working, error codes
- account: login, password, profile, settings, access
- other: anything that fits none of the above

Choose "other" rather than forcing a poor fit."""


def draft_answer(question: str, context_chunks: list[str]) -> str:
    """Draft a support reply for `question` using `context_chunks`."""
    settings = get_settings()

    context = "\n\n---\n\n".join(context_chunks)
    user_message = f"Context:\n{context}\n\nCustomer question: {question}"

    payload = {
        "model": settings.groq_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
    }

    try:
        response = httpx.post(
            _API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            timeout=60.0,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except httpx.HTTPError as exc:
        raise LLMError(f"generation request failed: {exc}") from exc
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError(f"unexpected generation response: {exc}") from exc

    if not content or not content.strip():
        raise LLMError("model returned empty content")

    return content.strip()


def _classification_schema() -> dict:
    """Build the strict JSON schema Groq requires, from the Pydantic model.

    Generated rather than hand-written so the schema sent to the model and
    the model used to validate the reply can never drift apart.
    """
    schema = TicketClassification.model_json_schema()
    schema["additionalProperties"] = False  # required by Groq strict mode
    return schema


def classify_ticket(subject: str, body: str) -> TicketCategory:
    """Classify a ticket. Returns OTHER on any failure — never raises.

    Classification is an enrichment, not a precondition: an unclassified
    ticket can still be retrieved for and drafted. Failing the whole ticket
    because this step broke would turn a nice-to-have into a hard dependency.

    Cached with no TTL. At temperature 0.0 the result is deterministic, and
    unlike a draft it depends only on the ticket text — the corpus can change
    without changing the category. The model name is in the key, so switching
    models produces new keys rather than stale hits.
    """
    settings = get_settings()
    cache_key = make_key("classify", settings.groq_model, f"{subject}\n{body}")

    cached = get_json(cache_key)
    if cached is not None:
        logger.info("classification cache hit")
        return TicketCategory(cached)

    payload = {
        "model": settings.groq_model,
        "messages": [
            {"role": "system", "content": _CLASSIFY_PROMPT},
            {"role": "user", "content": f"Subject: {subject}\n\nTicket: {body}"},
        ],
        "temperature": 0.0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "ticket_classification",
                "strict": True,
                "schema": _classification_schema(),
            },
        },
    }

    try:
        response = httpx.post(
            _API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            timeout=30.0,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        category = TicketClassification.model_validate_json(content).category
    except Exception as exc:
        logger.warning("classification failed, defaulting to OTHER: %s", exc)
        return TicketCategory.OTHER

    # Outside the try: a failure returns OTHER and caches nothing. Caching a
    # fallback would make one network blip permanent for that ticket text.
    set_json(cache_key, category.value)
    return category