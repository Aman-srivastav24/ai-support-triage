"""Similarity search over chunk embeddings."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.document import Document
from app.services.embeddings import embed_text

DEFAULT_TOP_K = 3


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk and how closely it matched the query."""

    chunk_id: str
    document_id: str
    document_title: str
    content: str
    similarity: float


def search_chunks(
    db: Session,
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """Return the top_k chunks most similar to `query`, best first."""
    query_embedding = embed_text(query, task_type="RETRIEVAL_QUERY", use_cache=True)

    distance = Chunk.embedding.cosine_distance(query_embedding)

    rows = db.execute(
        select(
            Chunk.id,
            Chunk.document_id,
            Document.title,
            Chunk.content,
            distance.label("distance"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.embedding.is_not(None))
        .order_by(distance)
        .limit(top_k)
    ).all()

    return [
        RetrievedChunk(
            chunk_id=str(row.id),
            document_id=str(row.document_id),
            document_title=row.title,
            content=row.content,
            similarity=1.0 - row.distance,
        )
        for row in rows
    ]