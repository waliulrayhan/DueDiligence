"""Retrieval service — fetch the most relevant chunks for a given question.

Design notes
------------
* LLM-independent: works with any backend (Groq, OpenAI, etc.).
* ``cached_filter_ids`` — callers that already know the document-ID list
  (e.g. the generate-all worker) can pass it in to skip the DB round-trip.
* Pinecone query runs in a thread pool via ``asyncio.to_thread`` so it never
  blocks the async event loop.
* Document filenames are fetched in a single IN-clause query (no N+1).
* Only chunks with ``relevance_score >= RELEVANCE_THRESHOLD`` are returned.
* Returns at most ``TOP_K`` chunks, ordered by relevance descending.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.indexing.vector_store import vector_store
from src.models.db_models import Document, Project
from src.models.enums import DocumentScope, DocumentStatus

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
TOP_K: int = 6
RELEVANCE_THRESHOLD: float = 0.25


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def retrieve_chunks(
    query: str,
    project: Project,
    db: AsyncSession,
    *,
    cached_filter_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return the top relevant chunks for *query* scoped to *project*.

    Parameters
    ----------
    query:
        The question text to search against the vector store.
    project:
        The ``Project`` ORM object (must have ``.scope`` and ``.document_ids``).
    db:
        An open async SQLAlchemy session.
    cached_filter_ids:
        Pre-computed list of document-ID strings to filter on.  When supplied
        the function skips the database query that would normally build this
        list — useful when generating answers in bulk.

    Returns
    -------
    list of dicts, each containing:
        ``chunk_id``, ``document_id``, ``text``, ``page_number``,
        ``relevance_score``, ``document_filename``
    """

    # ------------------------------------------------------------------ #
    # 1. Determine which document IDs to filter on                        #
    # ------------------------------------------------------------------ #
    filter_ids: list[str] | None

    if cached_filter_ids is not None:
        # Caller already resolved the list — skip the DB round-trip.
        filter_ids = cached_filter_ids if cached_filter_ids else None
    else:
        filter_ids = await _resolve_filter_ids(project, db)

    logger.debug(
        "retrieve_chunks | project={} scope={} filter_ids_count={}",
        project.id,
        project.scope,
        len(filter_ids) if filter_ids else "ALL",
    )

    # ------------------------------------------------------------------ #
    # 2. Query Pinecone in a thread (non-blocking)                        #
    # ------------------------------------------------------------------ #
    raw_chunks: list[dict[str, Any]] = await asyncio.to_thread(
        vector_store.search,
        query,
        TOP_K,
        filter_ids,
    )

    # ------------------------------------------------------------------ #
    # 3. Apply relevance threshold                                        #
    # ------------------------------------------------------------------ #
    chunks = [c for c in raw_chunks if c["relevance_score"] >= RELEVANCE_THRESHOLD]

    if not chunks:
        logger.debug(
            "retrieve_chunks | no chunks above threshold={} for query={!r}",
            RELEVANCE_THRESHOLD,
            query[:80],
        )
        return []

    # ------------------------------------------------------------------ #
    # 4. Batch-fetch document filenames (single DB query, no N+1)        #
    # ------------------------------------------------------------------ #
    chunks = await _attach_filenames(chunks, db)

    return chunks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_filter_ids(
    project: Project,
    db: AsyncSession,
) -> list[str] | None:
    """Return a list of document-ID strings to pass to Pinecone, or None.

    * ``ALL_DOCS``       → ``None`` (Pinecone searches across everything).
    * ``SELECTED_DOCS``  → the IDs stored on ``project.document_ids``.

    Only IDs whose documents are in ``READY`` status are included, so chunks
    from partially-indexed uploads are never surfaced.
    """

    if project.scope == DocumentScope.ALL_DOCS:
        return None

    # SELECTED_DOCS — validate that each ID exists and is READY
    raw_ids: list[str] = list(project.document_ids or [])
    if not raw_ids:
        logger.warning(
            "Project {} has scope=SELECTED_DOCS but no document_ids set.",
            project.id,
        )
        return []

    # Coerce to UUID objects for the IN clause (handles both str and UUID input)
    try:
        uuid_ids = [uuid.UUID(str(i)) for i in raw_ids]
    except ValueError as exc:
        logger.error("Invalid document UUID in project {}: {}", project.id, exc)
        return []

    result = await db.execute(
        select(Document.id).where(
            Document.id.in_(uuid_ids),
            Document.status == DocumentStatus.READY,
        )
    )
    ready_ids = [str(row) for row in result.scalars().all()]

    if len(ready_ids) < len(raw_ids):
        skipped = len(raw_ids) - len(ready_ids)
        logger.debug(
            "Project {} | skipped {} document(s) that are not READY.",
            project.id,
            skipped,
        )

    return ready_ids


async def _attach_filenames(
    chunks: list[dict[str, Any]],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    """Enrich each chunk dict with a ``document_filename`` key.

    Performs exactly one database query regardless of how many unique
    document IDs appear in *chunks*.
    """
    # Collect unique document IDs present in the result set
    unique_doc_ids: list[uuid.UUID] = []
    seen: set[str] = set()
    for chunk in chunks:
        doc_id_str = chunk.get("document_id", "")
        if doc_id_str and doc_id_str not in seen:
            seen.add(doc_id_str)
            try:
                unique_doc_ids.append(uuid.UUID(doc_id_str))
            except ValueError:
                logger.warning("Non-UUID document_id in chunk: {!r}", doc_id_str)

    if not unique_doc_ids:
        for chunk in chunks:
            chunk["document_filename"] = None
        return chunks

    # Single query for all needed documents
    result = await db.execute(
        select(Document.id, Document.original_name).where(
            Document.id.in_(unique_doc_ids)
        )
    )
    id_to_name: dict[str, str] = {
        str(row.id): row.original_name for row in result.all()
    }

    filtered: list[dict[str, Any]] = []
    for chunk in chunks:
        doc_id = chunk.get("document_id", "")
        if doc_id and doc_id not in id_to_name:
            # The document was indexed in the vector store but no longer exists
            # in the database (e.g. after a DB reset).  Drop this chunk so we
            # never try to insert a Citation that violates the FK constraint.
            logger.warning(
                "_attach_filenames | document_id={!r} not found in DB — "
                "dropping stale chunk (chunk_id={!r})",
                doc_id,
                chunk.get("chunk_id"),
            )
            continue
        chunk["document_filename"] = id_to_name.get(doc_id)
        filtered.append(chunk)

    return filtered
