"""The fake embedder must behave enough like a real one for retrieval tests
to mean something. These tests pin down that assumption once, directly,
so every test built on top of it can rely on it."""

import pytest

from app.graph.nodes import SIMILARITY_FLOOR
from app.models.chunk import Chunk

DOC = "Refunds are available within 14 days of the first charge."


def cosine(a: list[float], b: list[float]) -> float:
    """Both vectors are unit length, so cosine similarity is the dot product."""
    return sum(x * y for x, y in zip(a, b))


def test_vector_matches_the_database_column(fake_embedder):
    vector = fake_embedder.embed(DOC, task_type="RETRIEVAL_DOCUMENT")

    assert len(vector) == Chunk.__table__.c.embedding.type.dim
    assert cosine(vector, vector) == pytest.approx(1.0)


def test_same_text_gives_same_vector_every_time(fake_embedder):
    first = fake_embedder.embed(DOC, task_type="RETRIEVAL_DOCUMENT")
    second = fake_embedder.embed(DOC, task_type="RETRIEVAL_QUERY")

    assert first == second


def test_shared_words_clear_the_similarity_floor(fake_embedder):
    doc = fake_embedder.embed(DOC, task_type="RETRIEVAL_DOCUMENT")
    query = fake_embedder.embed(
        "Refunds are available within 14 days", task_type="RETRIEVAL_QUERY"
    )

    assert cosine(doc, query) >= SIMILARITY_FLOOR


def test_unrelated_words_fall_below_the_similarity_floor(fake_embedder):
    doc = fake_embedder.embed(DOC, task_type="RETRIEVAL_DOCUMENT")
    query = fake_embedder.embed(
        "Who won the football match last night", task_type="RETRIEVAL_QUERY"
    )

    assert cosine(doc, query) < SIMILARITY_FLOOR


def test_every_call_is_recorded(fake_embedder):
    fake_embedder.embed("one", task_type="RETRIEVAL_DOCUMENT")
    fake_embedder.embed("two", task_type="RETRIEVAL_QUERY")

    assert fake_embedder.calls == [
        ("one", "RETRIEVAL_DOCUMENT"),
        ("two", "RETRIEVAL_QUERY"),
    ]