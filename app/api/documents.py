"""Document upload endpoints. Admin only."""

from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from app.api.deps import AdminUser, DbSession
from app.schemas.document import DocumentRead
from app.services.documents import (
    DuplicateDocument,
    EmptyDocument,
    create_document,
    ingest_document,
)

router = APIRouter(prefix="/documents", tags=["documents"])
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"text/plain", "text/markdown", "application/octet-stream"}


@router.post(
    "",
    response_model=DocumentRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    background_tasks: BackgroundTasks,
    admin: AdminUser,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=255)] = None,
) -> DocumentRead:
    """Upload a document. Returns immediately; chunking runs in the background."""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type: {file.content_type}",
        )

    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_UPLOAD_BYTES} bytes",
        )

    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be valid UTF-8 text",
        ) from None

    try:
        document = create_document(
            db,
            title=title or file.filename or "Untitled",
            raw_text=raw_text,
            source_filename=file.filename,
            uploaded_by_id=admin.id,
        )
    except EmptyDocument:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File contains no text",
        ) from None
    except DuplicateDocument as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Identical document already exists: {exc}",
        ) from None

    background_tasks.add_task(ingest_document, document.id)
    return document


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(document_id: str, admin: AdminUser, db: DbSession) -> DocumentRead:
    """Check a document's ingestion status."""
    import uuid

    from app.models.document import Document

    try:
        parsed = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        ) from None

    document = db.get(Document, parsed)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )
    return document