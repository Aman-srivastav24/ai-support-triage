"""External AI providers behind small interfaces.

The rest of the app depends on these interfaces, not on Groq or Gemini
directly. The real implementations delegate to the existing functions in
llm.py and embeddings.py, so prompts, caching and error handling stay
exactly where they are. Tests replace these objects through FastAPI's
dependency_overrides; nothing here knows tests exist.
"""

from typing import Protocol

from app.schemas.classification import TicketCategory
from app.services.embeddings import embed_text
from app.services.llm import classify_ticket, draft_answer


class LLMClient(Protocol):
    """What the triage graph needs from a language model."""

    def classify(self, subject: str, body: str) -> TicketCategory: ...

    def draft(self, question: str, context_chunks: list[str]) -> str: ...


class Embedder(Protocol):
    """What retrieval and ingestion need from an embedding model."""

    def embed(
        self, text: str, *, task_type: str, use_cache: bool = False
    ) -> list[float]: ...


class GroqLLM:
    """Real LLM client. Thin wrapper over the Groq-backed functions."""

    def classify(self, subject: str, body: str) -> TicketCategory:
        return classify_ticket(subject, body)

    def draft(self, question: str, context_chunks: list[str]) -> str:
        return draft_answer(question, context_chunks)


class GeminiEmbedder:
    """Real embedder. Thin wrapper over the Gemini-backed function."""

    def embed(
        self, text: str, *, task_type: str, use_cache: bool = False
    ) -> list[float]:
        return embed_text(text, task_type=task_type, use_cache=use_cache)


def get_llm() -> LLMClient:
    """Dependency: the LLM client for this request. Overridden in tests."""
    return GroqLLM()


def get_embedder() -> Embedder:
    """Dependency: the embedder for this request. Overridden in tests."""
    return GeminiEmbedder()