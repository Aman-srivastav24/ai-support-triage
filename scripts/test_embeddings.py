"""Manual check of the embedding service. Not a test suite."""

import math
import time

from app.services.embeddings import embed_text


def magnitude(vector: list[float]) -> float:
    """Length of the vector. 1.0 means it is already normalised."""
    return math.sqrt(sum(value * value for value in vector))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (magnitude(a) * magnitude(b))


start = time.perf_counter()
doc = embed_text("Refunds are issued within 14 days of purchase.", task_type="RETRIEVAL_DOCUMENT")
elapsed = time.perf_counter() - start

print(f"dimensions: {len(doc)}")
print(f"magnitude:  {magnitude(doc):.6f}   (1.0 = normalised)")
print(f"latency:    {elapsed:.3f}s")

related = embed_text("How long do I have to get my money back?", task_type="RETRIEVAL_QUERY")
unrelated = embed_text("What time does the moon rise in Tokyo?", task_type="RETRIEVAL_QUERY")

print(f"\nsimilarity, related question:   {cosine_similarity(doc, related):.4f}")
print(f"similarity, unrelated question: {cosine_similarity(doc, unrelated):.4f}")