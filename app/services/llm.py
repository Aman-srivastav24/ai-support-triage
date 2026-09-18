"""Answer generation via the Groq API."""

import httpx

from app.core.config import get_settings

_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMError(Exception):
    """Raised when the language model provider fails or returns nothing usable."""


# NAIVE PROMPT — no grounding instruction. Replaced later today, deliberately.
_SYSTEM_PROMPT = """You are a support assistant drafting a reply for a human agent to review.

Rules:
- Answer ONLY using the context provided. The context is the complete set of information available to you.
- If the context does not contain the answer, say exactly: "The documentation does not cover this." Then stop. Do not suggest workarounds, next steps, or who to contact unless that information appears in the context.
- Never invent email addresses, phone numbers, prices, timeframes, processes, or policies.
- Do not use knowledge from your training. If it is not in the context, you do not know it.
- If the context partially answers the question, state what it does cover and say plainly which part is not covered.
- Be brief and factual. Do not add closing pleasantries."""


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