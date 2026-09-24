"""Run tickets through the triage graph directly, no web server.

Run: python scripts/test_graph.py
"""

import logging
import uuid

from app.db.session import SessionLocal
from app.graph.triage import build_triage_graph
from app.services.providers import GeminiEmbedder, GroqLLM

logging.basicConfig(level=logging.INFO, format="%(message)s")

CASES = [
    ("Refund window", "How many days do I have to request a refund after I am charged?"),
    ("Student discount", "Do you offer a student discount, and how do I apply for it?"),
    ("Sunday hours", "Are your offices open on Sundays?"),
]

db = SessionLocal()
try:
    graph = build_triage_graph(db, llm=GroqLLM(), embedder=GeminiEmbedder())

    for subject, body in CASES:
        print(f"\n{'=' * 70}\n{subject}\n{'=' * 70}")

        result = graph.invoke(
            {"ticket_id": uuid.uuid4(), "subject": subject, "body": body}
        )

        print(f"\ncategory   : {result['category'].value}")
        print(f"chunks     : {len(result['chunks'])}")
        print(f"confidence : {result['confidence']:.4f}")
        print(f"escalate   : {result['escalate']}")
        print(f"reason     : {result['escalation_reason']}")
        print(f"draft      : {result['draft'][:200]}")
finally:
    db.close()