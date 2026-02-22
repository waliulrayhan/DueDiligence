from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, field_serializer

# ---------------------------------------------------------------------------
# Annotated helper – coerces uuid.UUID (returned by SQLAlchemy) to plain str
# without breaking callers that already pass a str.
# ---------------------------------------------------------------------------
UUIDStr = Annotated[str, BeforeValidator(str)]

from src.models.enums import (
    AnswerStatus,
    DocumentScope,
    DocumentStatus,
    ProjectStatus,
    RequestStatus,
)

# ---------------------------------------------------------------------------
# Shared config – ORM mode enabled so models can be built from SQLAlchemy rows
# ---------------------------------------------------------------------------
_orm_config = ConfigDict(from_attributes=True)


# ===========================================================================
# REQUEST models
# ===========================================================================

class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    questionnaire_doc_id: str
    scope: DocumentScope = DocumentScope.ALL_DOCS
    document_ids: list[str] = []


class GenerateSingleAnswerRequest(BaseModel):
    project_id: str
    question_id: str


class GenerateAllAnswersRequest(BaseModel):
    project_id: str


class UpdateProjectRequest(BaseModel):
    project_id: str
    name: str | None = None
    description: str | None = None
    scope: DocumentScope | None = None
    document_ids: list[str] | None = None


class UpdateAnswerRequest(BaseModel):
    answer_id: str
    status: AnswerStatus
    manual_answer_text: str | None = None
    reviewer_note: str | None = None


class GroundTruthItem(BaseModel):
    """Single entry in the ground-truth list for evaluation requests."""
    question_id: str
    human_answer_text: str


class EvaluateRequest(BaseModel):
    project_id: str
    ground_truth: list[GroundTruthItem]  # [{question_id, human_answer_text}]


# ===========================================================================
# RESPONSE models
# ===========================================================================

class CitationResponse(BaseModel):
    model_config = _orm_config

    id: UUIDStr
    chunk_id: str | None          # plain Text column, not a UUID
    document_id: UUIDStr | None
    page_number: int | None
    excerpt_text: str | None
    relevance_score: float | None


class AnswerResponse(BaseModel):
    model_config = _orm_config

    id: UUIDStr
    question_id: UUIDStr
    ai_answer_text: str | None
    manual_answer_text: str | None
    answer_text: str | None
    can_answer: bool
    confidence_score: float
    status: AnswerStatus
    reviewer_note: str | None
    reviewed_at: datetime | None = None
    citations: list[CitationResponse] = []


class QuestionResponse(BaseModel):
    model_config = _orm_config

    id: UUIDStr
    section_name: str | None
    question_text: str
    question_order: int | None
    question_number: int | None = None
    answer: AnswerResponse | None = None


class ProjectResponse(BaseModel):
    model_config = _orm_config

    id: UUIDStr
    name: str
    description: str | None
    scope: DocumentScope
    status: ProjectStatus
    question_count: int = 0
    questions: list[QuestionResponse] = []
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, v: datetime) -> str:
        return v.isoformat()


class DocumentResponse(BaseModel):
    model_config = _orm_config

    id: UUIDStr
    original_name: str
    file_type: str | None
    status: DocumentStatus
    chunk_count: int
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, v: datetime) -> str:
        return v.isoformat()


class AsyncRequestResponse(BaseModel):
    model_config = _orm_config

    request_id: str
    status: RequestStatus
    error_message: str | None = None
    completed_at: datetime | None = None

    @field_serializer("completed_at")
    def serialize_completed_at(self, v: datetime | None) -> str | None:
        return v.isoformat() if v is not None else None


class EvaluationResultResponse(BaseModel):
    model_config = _orm_config

    question_id: UUIDStr
    similarity_score: float
    keyword_overlap: float
    overall_score: float
    explanation: str | None
