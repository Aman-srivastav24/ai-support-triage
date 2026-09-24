"""Document creation and ingestion. Knows nothing about HTTP."""

from __future__ import annotations

import hashlib
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.services.chunking import chunk_text
from app.services.providers import Embedder  # ← CHANGE (replaces embeddings import)

logger = logging.getLogger(__name__)


class DuplicateDocument(Exception):
    """Raised when a document with identical content already exists."""


class EmptyDocument(Exception):
    """Raised when the uploaded file has no usable text."""


def create_document(
    db: Session,
    *,
    title: str,
    raw_text: str,
    source_filename: str | None,
    uploaded_by_id: uuid.UUID,
) -> Document:
    """Store a document as pending. Ingestion happens separately."""
    if not raw_text.strip():
        raise EmptyDocument

    content_sha256 = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

    existing = db.execute(
        select(Document).where(Document.content_sha256 == content_sha256)
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateDocument(str(existing.id))

    document = Document(
        title=title,
        raw_text=raw_text,
        source_filename=source_filename,
        content_sha256=content_sha256,
        uploaded_by_id=uploaded_by_id,
        status=DocumentStatus.PENDING,
    )
    db.add(document)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateDocument(content_sha256) from exc

    db.refresh(document)
    return document


def ingest_document(
    document_id: uuid.UUID,
    *,
    embedder: Embedder,  # ← CHANGE
) -> None:
    """Chunk a document and store the chunks. Runs in the background.

    Opens its own session: the request's session is closed by the time
    this runs. The embedder is passed in by the route, so tests can
    substitute a fake without touching this function.
    """
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None:
            logger.error("ingest: document %s not found", document_id)
            return

        document.status = DocumentStatus.PROCESSING
        db.commit()

        try:
            chunks = chunk_text(document.raw_text)
            if not chunks:
                raise ValueError("document produced no chunks")

            for c in chunks:
                embedding = embedder.embed(  # ← CHANGE (was embed_text)
                    c.content, task_type="RETRIEVAL_DOCUMENT"
                )
                db.add(
                    Chunk(
                        document_id=document.id,
                        chunk_index=c.index,
                        content=c.content,
                        token_count=c.token_count,
                        embedding=embedding,
                    )
                )
                logger.info(
                    "ingest: embedded chunk %d/%d for document %s",
                    c.index + 1,
                    len(chunks),
                    document_id,
                )
            document.chunk_count = len(chunks)
            document.status = DocumentStatus.READY
            document.error_message = None
            db.commit()
            logger.info("ingest: document %s ready, %d chunks", document_id, len(chunks))

        except Exception as exc:
            db.rollback()
            document.status = DocumentStatus.FAILED
            document.error_message = str(exc)[:1000]
            db.commit()
            logger.exception("ingest: document %s failed", document_id)
    finally:
        db.close()