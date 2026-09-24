"""Embedding generation via the Gemini API."""

import logging
import math

import httpx

from app.core.config import get_settings
from app.services.cache import get_json, make_key, set_json

logger = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class EmbeddingError(Exception):
    """Raised when the embedding provider fails or returns an unusable response."""


def _normalise(vector: list[float]) -> list[float]:
    """Scale the vector to length 1 so cosine similarity behaves predictably."""
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        raise EmbeddingError("embedding has zero magnitude")
    return [value / magnitude for value in vector]


def _cache_key(text: str, task_type: str) -> str:
    """Key an embedding by everything that determines the vector.

    Model, task type and dimensions all change the output for identical
    text — Gemini embeds a query differently from a document — so all
    three belong in the key. Serving a query vector to a document lookup
    would corrupt results silently, with no error anywhere.
    """
    settings = get_settings()
    model_id = (
        f"{settings.gemini_embedding_model}"
        f"-{task_type}"
        f"-{settings.embedding_dimensions}"
    )
    return make_key("emb", model_id, text)


def embed_text(text: str, *, task_type: str, use_cache: bool = False) -> list[float]:
    """Return a single embedding vector for `text`.

    task_type is "RETRIEVAL_DOCUMENT" when storing a chunk,
    "RETRIEVAL_QUERY" when searching with a ticket.

    use_cache is opt-in rather than always-on because the two callers have
    opposite hit rates. Ingestion embeds each chunk once and would never
    read the key back. Ticket queries repeat constantly — customers ask the
    same questions — so caching pays there. The caller knows whether
    repetition is likely; this function does not.
    """
    if use_cache:
        cached = get_json(_cache_key(text, task_type))
        if cached is not None:
            logger.info("embedding cache hit")
            return cached

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

    vector = _normalise(values)

    if use_cache:
        # No TTL: this mapping is fixed for a given model, task type and
        # dimension count, all of which are in the key. A model change
        # produces new keys rather than stale hits.
        set_json(_cache_key(text, task_type), vector)

    return vector