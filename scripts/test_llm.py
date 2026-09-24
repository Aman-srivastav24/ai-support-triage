"""Manual check of the generation service against the naive prompt."""

import time

from app.db.session import SessionLocal
from app.services.llm import draft_answer
from app.services.retrieval import search_chunks
from app.services.providers import GeminiEmbedder
import sys

QUESTION = sys.argv[1] if len(sys.argv) > 1 else "How long do I have to request a refund on my subscription?"


def main() -> None:
    db = SessionLocal()
    try:
        hits = search_chunks(db, QUESTION, embedder=GeminiEmbedder(), top_k=3)

        print(f"Question: {QUESTION}\n")
        print("Retrieved:")
        for rank, hit in enumerate(hits, start=1):
            print(f"  {rank}. {hit.similarity:.4f}  {hit.document_title}")

        started = time.perf_counter()
        answer = draft_answer(QUESTION, [hit.content for hit in hits])
        elapsed = time.perf_counter() - started

        print(f"\nAnswer ({elapsed:.2f}s):\n{answer}")
    finally:
        db.close()


if __name__ == "__main__":
    main()