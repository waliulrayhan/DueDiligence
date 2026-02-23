from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.db_models import Answer, AsyncRequest, Document, Project, Question
from src.models.enums import (
    AnswerStatus,
    DocumentScope,
    DocumentStatus,
    ProjectStatus,
    RequestStatus,
)
from src.models.schemas import (
    AnswerResponse,
    AsyncRequestResponse,
    CreateProjectRequest,
    ProjectResponse,
    QuestionResponse,
    UpdateProjectRequest,
)
from src.services.questionnaire_parser import questionnaire_parser
from src.storage.database import AsyncSessionLocal, get_db

router = APIRouter(prefix="/projects", tags=["projects"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Extra response schema – not in the shared schemas file
# ---------------------------------------------------------------------------

class ProjectStatusResponse(BaseModel):
    project_id: str
    status: ProjectStatus
    question_count: int


# ---------------------------------------------------------------------------
# Background task — shared by /create and /update
# ---------------------------------------------------------------------------

async def setup_project_background(project_id: str, request_id: str) -> None:
    """Parse the questionnaire, persist questions, and seed pending answers.

    Status lifecycle:
        Project:      CREATED / OUTDATED → INDEXING → READY  (or ERROR)
        AsyncRequest: PENDING            → RUNNING  → COMPLETED (or FAILED)
    """
    async with AsyncSessionLocal() as db:
        try:
            # 1. Mark as RUNNING ─────────────────────────────────────────────
            await db.execute(
                update(Project)
                .where(Project.id == project_id)
                .values(status=ProjectStatus.INDEXING)
            )
            await db.execute(
                update(AsyncRequest)
                .where(AsyncRequest.id == request_id)
                .values(status=RequestStatus.RUNNING, started_at=_utcnow())
            )
            await db.commit()

            # 2. Load project + questionnaire document ────────────────────────
            project = await db.get(Project, project_id)
            if not project:
                raise RuntimeError(f"Project '{project_id}' not found.")

            doc = await db.get(Document, str(project.questionnaire_doc_id))
            if not doc:
                raise RuntimeError(
                    f"Questionnaire document '{project.questionnaire_doc_id}' not found."
                )

            logger.info(
                "setup_project: parsing questionnaire '{}' for project '{}'.",
                doc.original_name,
                project_id,
            )

            # 3. Parse questionnaire PDF ──────────────────────────────────────
            parsed = questionnaire_parser.parse(doc.file_path)
            logger.info("setup_project: {} questions extracted.", len(parsed))

            # 4. Delete existing questions (cascade deletes their answers) ────
            await db.execute(
                delete(Question).where(Question.project_id == project_id)
            )
            await db.flush()

            # 5. Bulk-insert questions in ONE statement (RETURNING id) ──────────
            # Then bulk-insert answers in ONE statement.
            # This avoids N round-trips over the cloud DB connection.
            question_rows = [
                {
                    "project_id": project_id,
                    "section_name": item["section_name"],
                    "question_text": item["question_text"],
                    "question_order": item["question_order"],
                    "question_number": item["question_number"],
                }
                for item in parsed
            ]
            q_result = await db.execute(
                insert(Question).returning(Question.id),
                question_rows,
            )
            question_ids = [str(row[0]) for row in q_result.fetchall()]

            answer_rows = [
                {
                    "project_id": project_id,
                    "question_id": qid,
                    "status": AnswerStatus.PENDING,
                    "can_answer": True,
                    "confidence_score": 0.0,
                }
                for qid in question_ids
            ]
            await db.execute(insert(Answer), answer_rows)

            # 6. Set Project → READY, AsyncRequest → COMPLETED ────────────────
            await db.execute(
                update(Project)
                .where(Project.id == project_id)
                .values(status=ProjectStatus.READY)
            )
            await db.execute(
                update(AsyncRequest)
                .where(AsyncRequest.id == request_id)
                .values(
                    status=RequestStatus.COMPLETED,
                    completed_at=_utcnow(),
                )
            )
            await db.commit()

            logger.info(
                "setup_project: project '{}' is READY with {} questions.",
                project_id,
                len(parsed),
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "setup_project failed for project '{}': {}", project_id, exc
            )
            await db.rollback()
            try:
                await db.execute(
                    update(Project)
                    .where(Project.id == project_id)
                    .values(status=ProjectStatus.ERROR)
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
                    "Failed to persist error state for project '{}'.", project_id
                )
            raise


# ---------------------------------------------------------------------------
# POST /create
# ---------------------------------------------------------------------------

@router.post("/create", status_code=202)
async def create_project(
    body: CreateProjectRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> AsyncRequestResponse:
    """Create a project, parse its questionnaire, and seed pending answers."""

    # 1. Validate questionnaire document ─────────────────────────────────────
    doc = await db.get(Document, body.questionnaire_doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Questionnaire document not found.",
        )
    if doc.status != DocumentStatus.READY:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Questionnaire document is not READY "
                f"(current status: {doc.status.value})."
            ),
        )

    # 2. Validate SELECTED_DOCS constraint ────────────────────────────────────
    if body.scope == DocumentScope.SELECTED_DOCS and not body.document_ids:
        raise HTTPException(
            status_code=422,
            detail="document_ids must not be empty when scope=SELECTED_DOCS.",
        )

    # 3. Create Project record ─────────────────────────────────────────────────
    project = Project(
        name=body.name,
        description=body.description,
        questionnaire_doc_id=body.questionnaire_doc_id,
        scope=body.scope,
        document_ids=body.document_ids,
        status=ProjectStatus.CREATED,
    )
    db.add(project)
    await db.flush()  # populate project.id

    # 4. Create AsyncRequest record ───────────────────────────────────────────
    req = AsyncRequest(
        request_type="setup_project",
        status=RequestStatus.PENDING,
        project_id=str(project.id),
    )
    db.add(req)
    await db.flush()  # populate req.id

    project_id = str(project.id)
    request_id = str(req.id)

    await db.commit()

    # 5. Launch background task ───────────────────────────────────────────────
    background_tasks.add_task(
        setup_project_background,
        project_id=project_id,
        request_id=request_id,
    )

    # 6. Return 202 ───────────────────────────────────────────────────────────
    return AsyncRequestResponse(
        request_id=request_id,
        status=RequestStatus.PENDING,
    )


# ---------------------------------------------------------------------------
# POST /update
# ---------------------------------------------------------------------------

@router.post("/update", status_code=202)
async def update_project(
    body: UpdateProjectRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> AsyncRequestResponse:
    """Update editable project fields, re-triggering setup when scope/docs change."""

    project = await db.get(Project, body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    needs_reindex = False

    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.scope is not None and body.scope != project.scope:
        project.scope = body.scope
        needs_reindex = True
    if (
        body.document_ids is not None
        and body.document_ids != list(project.document_ids or [])
    ):
        project.document_ids = body.document_ids
        needs_reindex = True

    # Validate SELECTED_DOCS constraint after applying changes ────────────────
    if project.scope == DocumentScope.SELECTED_DOCS and not project.document_ids:
        raise HTTPException(
            status_code=422,
            detail="document_ids must not be empty when scope=SELECTED_DOCS.",
        )

    if needs_reindex:
        project.status = ProjectStatus.CREATED

    # Always create an AsyncRequest to give the caller a trackable id ─────────
    req = AsyncRequest(
        request_type="setup_project",
        status=RequestStatus.PENDING,
        project_id=str(project.id),
    )
    db.add(req)
    await db.flush()

    # If no re-index is needed, complete the request inline ───────────────────
    if not needs_reindex:
        req.status = RequestStatus.COMPLETED
        req.completed_at = _utcnow()

    project_id = str(project.id)
    request_id = str(req.id)

    await db.commit()

    if needs_reindex:
        background_tasks.add_task(
            setup_project_background,
            project_id=project_id,
            request_id=request_id,
        )

    return AsyncRequestResponse(
        request_id=request_id,
        status=req.status,
    )


# ---------------------------------------------------------------------------
# GET / — list all projects with question_count
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
) -> list[ProjectResponse]:
    # Use a subquery for question counts — avoids eager-loading 300+ rows per
    # project and also avoids the ORM→Pydantic list coercion issue that arises
    # when Pydantic introspects an InstrumentedList via from_attributes.
    q_count_subq = (
        select(Question.project_id, func.count().label("qcount"))
        .group_by(Question.project_id)
        .subquery()
    )
    result = await db.execute(
        select(Project, q_count_subq.c.qcount)
        .outerjoin(q_count_subq, Project.id == q_count_subq.c.project_id)
        .order_by(Project.created_at.desc())
    )
    rows = result.all()

    responses: list[ProjectResponse] = []
    for project, qcount in rows:
        pr = ProjectResponse(
            id=str(project.id),
            name=project.name,
            description=project.description,
            scope=project.scope,
            status=project.status,
            question_count=qcount or 0,
            questions=[],
            created_at=project.created_at,
        )
        responses.append(pr)

    return responses


# ---------------------------------------------------------------------------
# GET /{project_id}/status   ← must come BEFORE /{project_id}
# ---------------------------------------------------------------------------

@router.get("/{project_id}/status", response_model=ProjectStatusResponse)
async def get_project_status(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> ProjectStatusResponse:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    count_result = await db.execute(
        select(func.count())
        .select_from(Question)
        .where(Question.project_id == project_id)
    )
    q_count = count_result.scalar() or 0

    return ProjectStatusResponse(
        project_id=str(project.id),
        status=project.status,
        question_count=q_count,
    )


# ---------------------------------------------------------------------------
# GET /{project_id} — full project detail with questions + answers
# ---------------------------------------------------------------------------

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    # Explicit queries — avoids the uselist=False SAWarning that arises when
    # selectinload is used with __allow_unmapped__ = True relationships.
    q_result = await db.execute(
        select(Question)
        .where(Question.project_id == project_id)
        .order_by(Question.question_order)
    )
    question_rows = q_result.scalars().all()

    # Load all answers in one query, keyed by question_id
    a_result = await db.execute(
        select(Answer)
        .where(Answer.project_id == project_id)
        .options(selectinload(Answer.citations))
    )
    answers_by_question: dict[str, Answer] = {
        str(a.question_id): a for a in a_result.scalars().all()
    }

    questions: list[QuestionResponse] = []
    for q in question_rows:
        answer_obj = answers_by_question.get(str(q.id))
        first_answer = (
            AnswerResponse.model_validate(answer_obj) if answer_obj else None
        )
        questions.append(
            QuestionResponse(
                id=str(q.id),
                section_name=q.section_name,
                question_text=q.question_text,
                question_order=q.question_order,
                question_number=q.question_number,
                answer=first_answer,
            )
        )

    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        description=project.description,
        scope=project.scope,
        status=project.status,
        question_count=len(questions),
        questions=questions,
        created_at=project.created_at,
    )
