from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from sqlalchemy import select, update

from src.indexing.parsers import document_parser
from src.indexing.vector_store import vector_store
from src.models.db_models import AsyncRequest, Document, Project
from src.models.enums import DocumentScope, DocumentStatus, ProjectStatus, RequestStatus
from src.storage.database import AsyncSessionLocal


def _utcnow() -> datetime:
    """Return a timezone-aware UTC datetime (replaces deprecated utcnow())."""
    return datetime.now(timezone.utc)


async def process_document_background(
    document_id: str,
    request_id: str,
    file_path: str,
    file_type: str,
    file_content: bytes | None = None,
) -> None:
    """Parse, chunk, embed, and index a document.

    Runs in a background task with its own DB session so it never shares
    the request-scoped session that will have been closed already.

    Status lifecycle:
        Document:     UPLOADING → INDEXING → READY  (or FAILED)
        AsyncRequest: PENDING   → RUNNING  → COMPLETED (or FAILED)
    """
    # On serverless platforms (Vercel) the background task may run in a fresh
    # Lambda invocation with an empty /tmp.  Re-materialize the file from the
    # bytes that were captured in the upload handler's memory.
    if file_content is not None:
        _p = Path(file_path)
        _p.parent.mkdir(parents=True, exist_ok=True)
        if not _p.exists():
            _p.write_bytes(file_content)
            logger.info("Re-wrote upload bytes to '{}' for background task.", file_path)

    async with AsyncSessionLocal() as db:
        try:
            # 1. Mark as RUNNING ─────────────────────────────────────────────
            await db.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status=DocumentStatus.INDEXING)
            )
            await db.execute(
                update(AsyncRequest)
                .where(AsyncRequest.id == request_id)
                .values(status=RequestStatus.RUNNING, started_at=_utcnow())
            )
            await db.commit()

            # 2. Load document record for logging ────────────────────────────
            doc = await db.get(Document, document_id)
            if not doc:
                raise RuntimeError(f"Document '{document_id}' not found in DB.")

            logger.info("Starting indexing for '{}'.", doc.original_name)

            # 3. Parse file into pages ────────────────────────────────────────
            pages = document_parser.parse_file(file_path, file_type)
            logger.info(
                "Parsed {} pages from '{}'.", len(pages), doc.original_name
            )

            # 4. Chunk pages ─────────────────────────────────────────────────
            chunks = document_parser.chunk_pages(pages)
            logger.info("Created {} chunks.", len(chunks))

            # 5. Embed and upsert to Pinecone ────────────────────────────────
            vector_store.add_chunks(document_id=document_id, chunks=chunks)
            logger.info("Upserted {} vectors to Pinecone.", len(chunks))

            # 6. Mark document READY ─────────────────────────────────────────
            await db.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status=DocumentStatus.READY, chunk_count=len(chunks))
            )

            # 7. OUTDATED TRIGGER ─────────────────────────────────────────────
            # Every project with scope=ALL_DOCS that is currently READY must be
            # flipped to OUTDATED so the UI prompts users to re-generate answers.
            result = await db.execute(
                select(Project).where(
                    Project.scope == DocumentScope.ALL_DOCS,
                    Project.status == ProjectStatus.READY,
                )
            )
            all_docs_projects = result.scalars().all()
            for project in all_docs_projects:
                project.status = ProjectStatus.OUTDATED
                logger.info(
                    "Project '{}' marked OUTDATED (new document indexed).",
                    project.id,
                )

            # 8. Mark request COMPLETED ──────────────────────────────────────
            await db.execute(
                update(AsyncRequest)
                .where(AsyncRequest.id == request_id)
                .values(
                    status=RequestStatus.COMPLETED,
                    completed_at=_utcnow(),
                )
            )
            await db.commit()
            logger.info("Indexing complete for '{}'.", doc.original_name)

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Indexing failed for document '{}': {}", document_id, exc
            )
            await db.rollback()
            # Best-effort: persist FAILED state even if the session is dirty
            try:
                await db.execute(
                    update(Document)
                    .where(Document.id == document_id)
                    .values(status=DocumentStatus.FAILED)
                )
                await db.execute(
                    update(AsyncRequest)
                    .where(AsyncRequest.id == request_id)
                    .values(
                        status=RequestStatus.FAILED,
                        error_message=str(exc),
                        completed_at=_utcnow(),
                    )
                )
                await db.commit()
            except Exception:
                logger.exception(
                    "Failed to persist error state for document '{}'.", document_id
                )
            raise
