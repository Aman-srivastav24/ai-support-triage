"""Measure retrieval quality across questions the docs do and don't answer."""

import time

from app.db.session import SessionLocal
from app.services.retrieval import search_chunks

QUESTIONS = [
    # --- clearly answered by the corpus ---
    ("IN-CORPUS", "How do I get a refund on my subscription?"),
    ("IN-CORPUS", "My card was declined, what does that mean?"),
    ("IN-CORPUS", "I am locked out of my account after too many tries"),
    ("IN-CORPUS", "How long does delivery to the UK take?"),
    ("IN-CORPUS", "What is the largest file I can upload?"),
    # --- plausible support questions the corpus does NOT answer ---
    ("NOT-IN-CORPUS", "Do you offer a student discount?"),
    ("NOT-IN-CORPUS", "How do I export all my data as a spreadsheet?"),
    ("NOT-IN-CORPUS", "What is your phone number for urgent issues?"),
    # --- completely unrelated ---
    ("UNRELATED", "What is the best way to cook rice?"),
    ("UNRELATED", "Who won the football match last night?"),
]


def main() -> None:
    db = SessionLocal()
    try:
        for label, question in QUESTIONS:
            started = time.perf_counter()
            results = search_chunks(db, question, top_k=3)
            elapsed = time.perf_counter() - started

            print(f"\n[{label}] {question}")
            print(f"  ({elapsed:.2f}s)")
            for rank, hit in enumerate(results, start=1):
                print(f"  {rank}. {hit.similarity:.4f}  {hit.document_title}")
    finally:
        db.close()


if __name__ == "__main__":
    main()