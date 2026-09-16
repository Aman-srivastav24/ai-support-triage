"""Split document text into overlapping token-based chunks."""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

CHUNK_SIZE_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
_ENCODING_NAME = "cl100k_base"

_encoding = tiktoken.get_encoding(_ENCODING_NAME)


@dataclass(frozen=True)
class TextChunk:
    """One piece of a document, ready to become a Chunk row."""

    index: int
    content: str
    token_count: int


def count_tokens(text: str) -> int:
    """How many tokens this text costs."""
    return len(_encoding.encode(text))


def chunk_text(
    text: str,
    *,
    chunk_size: int = CHUNK_SIZE_TOKENS,
    overlap: int = CHUNK_OVERLAP_TOKENS,
) -> list[TextChunk]:
    """Split text into overlapping chunks of roughly chunk_size tokens."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap must be >= 0 and < chunk_size")

    tokens = _encoding.encode(text)
    if not tokens:
        return []

    step = chunk_size - overlap
    chunks: list[TextChunk] = []

    for index, start in enumerate(range(0, len(tokens), step)):
        window = tokens[start : start + chunk_size]
        chunks.append(
            TextChunk(
                index=index,
                content=_encoding.decode(window),
                token_count=len(window),
            )
        )
        if start + chunk_size >= len(tokens):
            break

    return chunks