"""Redis caching. The only module that knows Redis exists.

Cache failures are never fatal: a miss and an outage look the same to the
caller, which is slower but correct. Redis is declared non-critical in
config (redis_url has a default) and this module honours that.
"""

import hashlib
import json
import logging
from typing import Any

import redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None


def _get_client() -> redis.Redis | None:
    """Return a Redis client, or None if one cannot be created.

    Built once and reused. The connection itself is lazy — redis-py does
    not connect until a command is issued — so a Redis that is down at
    startup does not prevent the app from starting.
    """
    global _client
    if _client is None:
        try:
            _client = redis.from_url(
                get_settings().redis_url, decode_responses=True
            )
        except Exception as exc:
            logger.warning("redis client could not be created: %s", exc)
            return None
    return _client


def make_key(namespace: str, model: str, text: str) -> str:
    """Build a cache key: namespace, model, and a hash of the text.

    The model is part of the key because a cached value is only valid for
    the model that produced it. Swapping models must not silently serve
    values computed by the old one — a real risk here, since Groq retired
    a model mid-project.

    The text is hashed because keys must be short and safe, and a ticket
    body can be 5000 characters of arbitrary input.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{namespace}:{model}:{digest}"


def get_json(key: str) -> Any | None:
    """Read and decode a cached value. Returns None on miss or any failure."""
    client = _get_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception as exc:
        logger.warning("cache read failed for %s: %s", key, exc)
        return None


def set_json(key: str, value: Any, ttl_seconds: int | None = None) -> None:
    """Store a value as JSON. Silently does nothing on failure."""
    client = _get_client()
    if client is None:
        return
    try:
        client.set(key, json.dumps(value), ex=ttl_seconds)
    except Exception as exc:
        logger.warning("cache write failed for %s: %s", key, exc)