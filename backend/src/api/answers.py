"""Answers API — generate, review, and query AI-generated due-diligence answers.

Routes
------
POST /answers/generate-single    — generate answer for one question (sync)
POST /answers/generate-all       — kick off bulk generation (async, 202)
POST /answers/update             — reviewer approve / reject / manual-edit
GET  /answers/{project_id}                 — all answers for a project
GET  /answers/{answer_id}/audit            — audit trail for one answer
GET  /answers/{project_id}/{question_id}   — single answer with full detail
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.db_models import (
    Answer,
    AnswerAuditLog,
    AsyncRequest,
    Citation,
    Document,
    Project,
    Question,
)
from src.models.enums import (
    AnswerStatus,
    DocumentScope,
    DocumentStatus,
    RequestStatus,
)
from src.models.schemas import (
    AnswerResponse,
    AsyncRequestResponse,
    GenerateAllAnswersRequest,
    GenerateSingleAnswerRequest,
    UpdateAnswerRequest,
)
from src.services.llm_client import generate_answer
from src.services.retrieval_service import retrieve_chunks
from src.storage.database import AsyncSessionLocal, get_db

router = APIRouter(prefix="/answers", tags=["answers"])

# Limit concurrent LLM calls in generate-all (respects Groq free-tier ~30 req/min)
_GENERATE_ALL_CONCURRENCY = 5


# ---------------------------------------------------------------------------
# Local response schema — audit log entries
# ---------------------------------------------------------------------------

class AuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    answer_id: str
    old_status: str | None
    new_status: str | None
    changed_by: str
    change_note: str | None
    changed_at: datetime

    @field_serializer("changed_at")
    def _fmt_changed_at(self, v: datetime) -> str:
        return v.isoformat()

    @field_serializer("id", "answer_id")
    def _fmt_uuids(self, v: Any) -> str:
        return str(v)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _citations_from_result(
    result: dict[str, Any],
    answer_id: Any,
) -> list[Citation]:
    """Map LLM result citations to ORM Citation objects."""
    return [
        Citation(
            answer_id=answer_id,
            document_id=(
                uuid.UUID(c["document_id"]) if c.get("document_id") else None
            ),
            chunk_id=c.get("chunk_id"),
            page_number=c.get("page_number"),
            excerpt_text=c.get("excerpt_text"),
            relevance_score=c.get("relevance_score"),
        )
        for c in result.get("citations", [])
    ]


async def _upsert_answer(
    db: AsyncSession,
    *,
    project_id: str,
    question_id: str,
    result: dict[str, Any],
    change_note: str = "AI answer generated",
) -> Answer:
    """Create-or-update the Answer row, replace Citations, append AuditLog.

    Rule: ``ai_answer_text`` is set exactly once (on first generation) and
    is never overwritten by subsequent calls.  ``answer_text`` tracks the
    current "active" answer shown in the UI.
    """
    ans_q = await db.execute(
        select(Answer)
        .where(
            Answer.question_id == question_id,
            Answer.project_id == project_id,
        )
        .options(selectinload(Answer.citations))
    )
    answer: Answer | None = ans_q.scalar_one_or_none()
    old_status: AnswerStatus | None = answer.status if answer else None

    if answer is None:
        answer = Answer(
            project_id=project_id,
            question_id=question_id,
            ai_answer_text=result["answer_text"],
            answer_text=result["answer_text"],
            can_answer=result["can_answer"],
            confidence_score=result["confidence_score"],
            status=AnswerStatus.GENERATED,
        )
        db.add(answer)
        await db.flush()  # populate answer.id from server default
    else:
        # Preserve the original AI answer for audit purposes
        if answer.ai_answer_text is None:
            answer.ai_answer_text = result["answer_text"]
        answer.answer_text = result["answer_text"]
        answer.can_answer = result["can_answer"]
        answer.confidence_score = result["confidence_score"]
        answer.status = AnswerStatus.GENERATED
        await db.flush()

    # Replace citations atomically
    await db.execute(delete(Citation).where(Citation.answer_id == answer.id))
    raw_citations = _citations_from_result(result, answer.id)
    # Safety-net: verify every document_id referenced by a citation actually
    # exists in the DB — stale Pinecone entries can cause FK violations.
    if raw_citations:
        needed_ids = [c.document_id for c in raw_citations if c.document_id is not None]
        if needed_ids:
            valid_q = await db.execute(
                select(Document.id).where(Document.id.in_(needed_ids))
            )
            valid_ids: set[Any] = set(valid_q.scalars().all())
            dropped = [
                c for c in raw_citations
                if c.document_id is not None and c.document_id not in valid_ids
            ]
            if dropped:
                logger.warning(
                    "_upsert_answer | dropping {} citation(s) with stale document_ids: {}",
                    len(dropped),
                    [str(c.document_id) for c in dropped],
                )
            raw_citations = [
                c for c in raw_citations
                if c.document_id is None or c.document_id in valid_ids
            ]
    for citation in raw_citations:
        db.add(citation)

    # Append audit log entry
    db.add(
        AnswerAuditLog(
            answer_id=answer.id,
            old_status=old_status.value if old_status else None,
            new_status=AnswerStatus.GENERATED.value,
            changed_by="system",
            change_note=change_note,
        )
    )

    return answer


# ---------------------------------------------------------------------------
# POST /generate-single
# ---------------------------------------------------------------------------

@router.post("/generate-single", response_model=AnswerResponse)
async def generate_single(
    body: GenerateSingleAnswerRequest,
    db: AsyncSession = Depends(get_db),
) -> AnswerResponse:
    """Generate (or regenerate) an AI answer for a single question."""

    # 1. Load and validate ───────────────────────────────────────────────────
    project = await db.get(Project, body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    question = await db.get(Question, body.question_id)
    if not question or str(question.project_id) != body.project_id:
        raise HTTPException(status_code=404, detail="Question not found in this project.")

    # 2. Retrieve relevant document chunks ───────────────────────────────────
    context_chunks = await retrieve_chunks(question.question_text, project, db)

    # 3. Generate answer via LLM ─────────────────────────────────────────────
    try:
        result = await generate_answer(question.question_text, context_chunks)
    except Exception as exc:
        err_str = str(exc)
        if "429" in err_str or "rate_limit_exceeded" in err_str:
            raise HTTPException(
                status_code=429,
                detail=f"LLM rate limit reached — please wait before retrying. ({err_str[:200]})",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=f"LLM call failed: {err_str[:200]}",
        ) from exc

    # 4–6. Upsert answer + citations + audit log ─────────────────────────────
    answer = await _upsert_answer(
        db,
        project_id=body.project_id,
        question_id=body.question_id,
        result=result,
        change_note="AI answer generated via generate-single",
    )
    await db.commit()

    # 7. Reload with citations to build the response ─────────────────────────
    # Do NOT call db.refresh() here — it triggers a lazy-load of `citations`
    # (SAWarning: uselist=False). Use an explicit selectinload query instead.
    ans_q = await db.execute(
        select(Answer)
        .where(Answer.id == answer.id)
        .options(selectinload(Answer.citations))
    )
    answer = ans_q.scalar_one()

    logger.info(
        "generate-single: project={} question={} can_answer={} confidence={}",
        body.project_id,
        body.question_id,
        result["can_answer"],
        result["confidence_score"],
    )
    return AnswerResponse.model_validate(answer)


# ---------------------------------------------------------------------------
# POST /generate-all (202 async)
# ---------------------------------------------------------------------------

@router.post("/generate-all", status_code=202, response_model=AsyncRequestResponse)
async def generate_all(
    body: GenerateAllAnswersRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> AsyncRequestResponse:
    """Kick off bulk answer generation as a background task."""

    project = await db.get(Project, body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    req = AsyncRequest(
        request_type="generate_all",
        status=RequestStatus.PENDING,
        project_id=body.project_id,
    )
    db.add(req)
    await db.flush()
    request_id = str(req.id)
    await db.commit()

    background_tasks.add_task(
        generate_all_background,
        project_id=body.project_id,
        request_id=request_id,
        max_questions=body.max_questions,
    )

    return AsyncRequestResponse(request_id=request_id, status=RequestStatus.PENDING)


# ---------------------------------------------------------------------------
# Background worker — generate_all_background
# ---------------------------------------------------------------------------

async def generate_all_background(
    project_id: str,
    request_id: str,
    max_questions: int = 0,
) -> None:
    """Process all (or up to *max_questions*) questions concurrently.

    Strategy
    --------
    * Load project + questions once — close the session.
    * Pre-compute ``cached_filter_ids`` so retrieval_service skips a DB
      query on every question iteration.
    * Each question runs inside ``asyncio.Semaphore(5)`` with its own
      DB session — safe for concurrent writes.
    * Individual question failures are logged but do NOT abort the batch.
    * AsyncRequest is marked COMPLETED (or FAILED on catastrophic error).
    """

    # Phase 1 ── load context, mark RUNNING ──────────────────────────────────
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(AsyncRequest)
                .where(AsyncRequest.id == request_id)
                .values(status=RequestStatus.RUNNING, started_at=_utcnow())
            )
            await db.commit()

            project = await db.get(Project, project_id)
            if not project:
                raise RuntimeError(f"Project '{project_id}' not found.")

            q_result = await db.execute(
                select(Question)
                .where(Question.project_id == project_id)
                .order_by(Question.question_order)
            )
            questions: list[Question] = list(q_result.scalars().all())

            # Pre-compute filter IDs for the entire batch
            if project.scope == DocumentScope.ALL_DOCS:
                # Empty list → retrieval_service converts to None (no Pinecone filter)
                cached_filter_ids: list[str] = []
            else:
                raw_ids = [uuid.UUID(str(i)) for i in (project.document_ids or [])]
                if raw_ids:
                    id_result = await db.execute(
                        select(Document.id).where(
                            Document.id.in_(raw_ids),
                            Document.status == DocumentStatus.READY,
                        )
                    )
                    cached_filter_ids = [str(r) for r in id_result.scalars().all()]
                else:
                    cached_filter_ids = []

        # Optionally cap question count
        if max_questions > 0:
            questions = questions[:max_questions]

        logger.info(
            "generate_all: project={} questions={} cached_filter_ids_count={}",
            project_id,
            len(questions),
            len(cached_filter_ids) if cached_filter_ids else "ALL",
        )

    except Exception as exc:
        logger.exception("generate_all: failed during setup for project '{}': {}", project_id, exc)
        async with AsyncSessionLocal() as db:
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
        return

    # Phase 2 ── process questions concurrently ──────────────────────────────
    semaphore = asyncio.Semaphore(_GENERATE_ALL_CONCURRENCY)
    failed_count = 0

    async def _process_question(question: Question) -> None:
        nonlocal failed_count
        q_id = str(question.id)
        q_text = question.question_text

        async with semaphore:
            # Retry up to 3 times on 429 rate-limit errors.
            # Parse "try again in Xs" from the Groq error; if the wait exceeds
            # _MAX_RETRY_WAIT_SECS we skip the question rather than blocking.
            _MAX_RETRIES = 3
            _MAX_RETRY_WAIT_SECS = 300  # 5 minutes — skip if daily limit hit

            for attempt in range(_MAX_RETRIES):
                try:
                    async with AsyncSessionLocal() as db:
                        # Re-load project within this session (required for ORM binding)
                        proj = await db.get(Project, project_id)
                        if not proj:
                            raise RuntimeError("Project disappeared during generate-all.")

                        chunks = await retrieve_chunks(
                            q_text,
                            proj,
                            db,
                            cached_filter_ids=cached_filter_ids,
                        )
                        result = await generate_answer(q_text, chunks)

                        await _upsert_answer(
                            db,
                            project_id=project_id,
                            question_id=q_id,
                            result=result,
                            change_note="AI answer generated via generate-all",
                        )
                        await db.commit()

                    logger.debug(
                        "generate_all: question={} can_answer={} confidence={}",
                        q_id,
                        result["can_answer"],
                        result["confidence_score"],
                    )
                    break  # success — exit retry loop

                except Exception as exc:  # noqa: BLE001
                    err_str = str(exc)
                    is_rate_limit = "429" in err_str or "rate_limit_exceeded" in err_str

                    if is_rate_limit and attempt < _MAX_RETRIES - 1:
                        # Try to parse the suggested wait from the error message
                        import re as _re
                        m = _re.search(r"try again in (\d+(?:\.\d+)?)([smh])", err_str)
                        if m:
                            val, unit = float(m.group(1)), m.group(2)
                            wait_secs = val * {"s": 1, "m": 60, "h": 3600}[unit]
                        else:
                            wait_secs = 60.0  # default back-off

                        if wait_secs <= _MAX_RETRY_WAIT_SECS:
                            logger.warning(
                                "generate_all: 429 rate-limit on question={} — "
                                "waiting {:.0f}s before retry {}/{}.",
                                q_id, wait_secs, attempt + 1, _MAX_RETRIES,
                            )
                            await asyncio.sleep(wait_secs)
                            continue  # retry
                        else:
                            logger.error(
                                "generate_all: 429 daily token limit on question={} — "
                                "retry wait {:.0f}s exceeds threshold, skipping.",
                                q_id, wait_secs,
                            )

                    # Non-retryable error or retries exhausted
                    failed_count += 1
                    logger.error(
                        "generate_all: question='{}' failed — skipping. Error: {}",
                        q_id,
                        exc,
                    )
                    break

    await asyncio.gather(*[_process_question(q) for q in questions])

    # Phase 3 ── finalise AsyncRequest ───────────────────────────────────────
    async with AsyncSessionLocal() as db:
        final_status = RequestStatus.COMPLETED
        error_msg: str | None = None

        if failed_count > 0:
            error_msg = f"{failed_count}/{len(questions)} question(s) failed — see logs."
            logger.warning("generate_all: completed with {} failure(s) for project={}.", failed_count, project_id)

        await db.execute(
            update(AsyncRequest)
            .where(AsyncRequest.id == request_id)
            .values(
                status=final_status,
                error_message=error_msg,
                completed_at=_utcnow(),
            )
        )
        await db.commit()

    logger.info(
        "generate_all: DONE project={} total={} failed={}",
        project_id,
        len(questions),
        failed_count,
    )


# ---------------------------------------------------------------------------
# POST /update
# ---------------------------------------------------------------------------

@router.post("/update", response_model=AnswerResponse)
async def update_answer(
    body: UpdateAnswerRequest,
    db: AsyncSession = Depends(get_db),
) -> AnswerResponse:
    """Reviewer approves, rejects, or manually edits an answer."""

    # Validation ─────────────────────────────────────────────────────────────
    if body.status == AnswerStatus.REJECTED:
        if not body.reviewer_note or len(body.reviewer_note.strip()) < 5:
            raise HTTPException(
                status_code=400,
                detail="reviewer_note is required when rejecting an answer (min 5 chars).",
            )
    if body.status == AnswerStatus.MANUAL_UPDATED:
        if not body.manual_answer_text or len(body.manual_answer_text.strip()) < 5:
            raise HTTPException(
                status_code=400,
                detail="manual_answer_text is required for MANUAL_UPDATED (min 5 chars).",
            )

    # Load answer ─────────────────────────────────────────────────────────────
    ans_result = await db.execute(
        select(Answer)
        .where(Answer.id == body.answer_id)
        .options(selectinload(Answer.citations))
    )
    answer: Answer | None = ans_result.scalar_one_or_none()
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found.")

    old_status = answer.status

    # Apply update rules ──────────────────────────────────────────────────────
    if body.status == AnswerStatus.MANUAL_UPDATED:
        # Manual text provided — update both the display text and the manual slot.
        # ai_answer_text is intentionally left untouched.
        answer.manual_answer_text = body.manual_answer_text
        answer.answer_text = body.manual_answer_text

    elif body.status == AnswerStatus.CONFIRMED:
        # Reviewer approved the AI answer — answer_text stays as-is.
        pass

    answer.status = body.status
    answer.reviewer_note = body.reviewer_note
    answer.reviewed_at = _utcnow()

    # Audit log ───────────────────────────────────────────────────────────────
    db.add(
        AnswerAuditLog(
            answer_id=answer.id,
            old_status=old_status.value,
            new_status=body.status.value,
            changed_by="reviewer",
            change_note=body.reviewer_note or f"Status changed to {body.status.value}",
        )
    )

    await db.commit()

    # Reload with citations (no db.refresh() — that would lazy-load citations)
    ans_result = await db.execute(
        select(Answer)
        .where(Answer.id == answer.id)
        .options(selectinload(Answer.citations))
    )
    return AnswerResponse.model_validate(ans_result.scalar_one())


# ---------------------------------------------------------------------------
# GET /{project_id} — all answers for a project (with citations)
# ---------------------------------------------------------------------------

@router.get("/{project_id}", response_model=list[AnswerResponse])
async def list_project_answers(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[AnswerResponse]:
    """Return all answers (with citations) for every question in a project."""

    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    result = await db.execute(
        select(Answer)
        .where(Answer.project_id == project_id)
        .options(selectinload(Answer.citations))
        .order_by(Answer.question_id)
    )
    answers = result.scalars().all()
    return [AnswerResponse.model_validate(a) for a in answers]


# ---------------------------------------------------------------------------
# GET /{answer_id}/audit — audit trail for one answer
# NOTE: registered before /{project_id}/{question_id} so the literal
#       path segment "audit" takes precedence over the variable one.
# ---------------------------------------------------------------------------

@router.get("/{answer_id}/audit", response_model=list[AuditLogEntry])
async def get_answer_audit(
    answer_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogEntry]:
    """Return the full audit log for a given answer."""

    answer = await db.get(Answer, answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found.")

    result = await db.execute(
        select(AnswerAuditLog)
        .where(AnswerAuditLog.answer_id == answer_id)
        .order_by(AnswerAuditLog.changed_at.asc())
    )
    entries = result.scalars().all()
    return [AuditLogEntry.model_validate(e) for e in entries]


# ---------------------------------------------------------------------------
# GET /{project_id}/{question_id} — single answer with full detail
# ---------------------------------------------------------------------------

@router.get("/{project_id}/{question_id}", response_model=AnswerResponse)
async def get_answer_for_question(
    project_id: str,
    question_id: str,
    db: AsyncSession = Depends(get_db),
) -> AnswerResponse:
    """Return the answer (with citations) for a specific question in a project."""

    result = await db.execute(
        select(Answer)
        .where(
            Answer.project_id == project_id,
            Answer.question_id == question_id,
        )
        .options(selectinload(Answer.citations))
    )
    answer: Answer | None = result.scalar_one_or_none()
    if not answer:
        raise HTTPException(
            status_code=404,
            detail="Answer not found for this project/question combination.",
        )
    return AnswerResponse.model_validate(answer)
