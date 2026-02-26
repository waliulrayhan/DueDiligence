from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.indexing.vector_store import vector_store
from src.models.db_models import AsyncRequest, Document
from src.models.enums import DocumentStatus, RequestStatus
from src.models.schemas import AsyncRequestResponse, DocumentResponse
from src.storage.database import get_db
from src.workers.indexing_worker import process_document_background

router = APIRouter(prefix="/documents", tags=["documents"])

# ---------------------------------------------------------------------------
# Allowed file types
# ---------------------------------------------------------------------------
_ALLOWED_EXTENSIONS = {"pdf", "docx"}


def _get_extension(filename: str) -> str | None:
    """Return lower-cased extension without the dot, or None if absent."""
    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix if suffix else None


# ---------------------------------------------------------------------------
# POST / — upload & index a document
# ---------------------------------------------------------------------------

@router.post("/", status_code=202)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> AsyncRequestResponse:
    """Upload a PDF or DOCX, persist metadata, and kick off async indexing."""

    # 1. Validate file type ──────────────────────────────────────────────────
    ext = _get_extension(file.filename or "")
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(_ALLOWED_EXTENSIONS)}.",
        )

    # 2. Save file ───────────────────────────────────────────────────────────
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    unique_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = upload_dir / unique_filename

    contents = await file.read()
    file_path.write_bytes(contents)
    logger.info("Saved upload to '{}'.", file_path)

    # 3. Create Document record ──────────────────────────────────────────────
    doc = Document(
        filename=unique_filename,
        original_name=file.filename,
        file_path=str(file_path),
        file_type=ext,
        status=DocumentStatus.UPLOADING,
        chunk_count=0,
    )
    db.add(doc)
    await db.flush()  # populate doc.id before using it

    # 4. Create AsyncRequest record ──────────────────────────────────────────
    req = AsyncRequest(
        request_type="index_document",
        status=RequestStatus.PENDING,
        project_id=None,
    )
    db.add(req)
    await db.flush()  # populate req.id

    # Snapshot IDs as strings before the session closes
    document_id = str(doc.id)
    request_id = str(req.id)

    await db.commit()

    # 5. Launch background task ──────────────────────────────────────────────
    # Pass file bytes explicitly so the worker can re-write them to /tmp on
    # serverless platforms where a fresh Lambda invocation has an empty /tmp.
    background_tasks.add_task(
        process_document_background,
        document_id=document_id,
        request_id=request_id,
        file_path=str(file_path),
        file_type=ext,
        file_content=contents,
    )

    # 6. Return 202 immediately ──────────────────────────────────────────────
    return AsyncRequestResponse(
        request_id=request_id,
        status=RequestStatus.PENDING,
    )


# ---------------------------------------------------------------------------
# GET / — list all documents
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    db: AsyncSession = Depends(get_db),
) -> list[DocumentResponse]:
    result = await db.execute(
        select(Document).order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return [DocumentResponse.model_validate(d) for d in docs]


# ---------------------------------------------------------------------------
# GET /{document_id} — get a single document
# ---------------------------------------------------------------------------

@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return DocumentResponse.model_validate(doc)


# ---------------------------------------------------------------------------
# DELETE /{document_id} — delete document record + vectors
# ---------------------------------------------------------------------------

@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Remove vectors from Pinecone first (non-fatal if it fails)
    try:
        vector_store.delete_document(document_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not delete Pinecone vectors for document '{}': {}", document_id, exc
        )

    # Remove the file from disk (non-fatal)
    try:
        file_path = Path(doc.file_path)
        if file_path.exists():
            file_path.unlink()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not delete file '{}': {}", doc.file_path, exc)

    await db.delete(doc)
    await db.commit()

