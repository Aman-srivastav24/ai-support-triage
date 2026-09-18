"""Embedding generation via the Gemini API."""

import httpx
import math

from app.core.config import get_settings

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class EmbeddingError(Exception):
    """Raised when the embedding provider fails or returns an unusable response."""

def _normalise(vector: list[float]) -> list[float]:
    """Scale the vector to length 1 so cosine similarity behaves predictably."""
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        raise EmbeddingError("embedding has zero magnitude")
    return [value / magnitude for value in vector]


def embed_text(text: str, *, task_type: str) -> list[float]:
    """Return a single embedding vector for `text`.

    task_type is "RETRIEVAL_DOCUMENT" when storing a chunk,
    "RETRIEVAL_QUERY" when searching with a ticket.
    """
    settings = get_settings()
    url = f"{_API_BASE}/models/{settings.gemini_embedding_model}:embedContent"

    payload = {
        "model": f"models/{settings.gemini_embedding_model}",
        "content": {"parts": [{"text": text}]},
        "taskType": task_type,
        "outputDimensionality": settings.embedding_dimensions,
    }

    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"x-goog-api-key": settings.gemini_api_key},
            timeout=30.0,
        )
        response.raise_for_status()
        values = response.json()["embedding"]["values"]
    except httpx.HTTPError as exc:
        raise EmbeddingError(f"embedding request failed: {exc}") from exc
    except (KeyError, ValueError) as exc:
        raise EmbeddingError(f"unexpected embedding response: {exc}") from exc

    if len(values) != settings.embedding_dimensions:
        raise EmbeddingError(
            f"expected {settings.embedding_dimensions} dimensions, got {len(values)}"
        )

    return _normalise(values)