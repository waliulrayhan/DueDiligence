from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text

from src.models.enums import (
    AnswerStatus,
    DocumentScope,
    DocumentStatus,
    ProjectStatus,
    RequestStatus,
)
from src.storage.database import Base

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_uuid_pk = lambda: sa.Column(
    UUID(as_uuid=True),
    primary_key=True,
    server_default=text("gen_random_uuid()"),
)

_now = lambda: sa.Column(
    sa.DateTime(timezone=True),
    server_default=sa.func.now(),
    nullable=False,
)


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------
class Document(Base):
    __tablename__ = "documents"
    __allow_unmapped__ = True

    id = _uuid_pk()
    filename = sa.Column(sa.Text, nullable=False)
    original_name = sa.Column(sa.Text, nullable=False)
    file_path = sa.Column(sa.Text, nullable=False)
    file_type = sa.Column(sa.Text, nullable=True)  # pdf / docx
    status = sa.Column(
        sa.Enum(DocumentStatus, name="documentstatus"),
        nullable=False,
        default=DocumentStatus.UPLOADING,
        server_default=DocumentStatus.UPLOADING.value,
    )
    chunk_count = sa.Column(sa.Integer, nullable=False, default=0, server_default="0")
    created_at = _now()
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    # Relationships
    citations: list[Citation] = relationship("Citation", back_populates="document")


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------
class Project(Base):
    __tablename__ = "projects"
    __allow_unmapped__ = True

    id = _uuid_pk()
    name = sa.Column(sa.Text, nullable=False)
    description = sa.Column(sa.Text, nullable=True)
    questionnaire_doc_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    scope = sa.Column(
        sa.Enum(DocumentScope, name="documentscope"),
        nullable=False,
        default=DocumentScope.ALL_DOCS,
        server_default=DocumentScope.ALL_DOCS.value,
    )
    status = sa.Column(
        sa.Enum(ProjectStatus, name="projectstatus"),
        nullable=False,
        default=ProjectStatus.CREATED,
        server_default=ProjectStatus.CREATED.value,
    )
    # List of document UUIDs used when scope=SELECTED_DOCS
    document_ids = sa.Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at = _now()
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    # Relationships
    questionnaire_doc: Document = relationship(
        "Document",
        foreign_keys=[questionnaire_doc_id],
    )
    questions: list[Question] = relationship(
        "Question", back_populates="project", cascade="all, delete-orphan"
    )
    answers: list[Answer] = relationship(
        "Answer", back_populates="project", cascade="all, delete-orphan"
    )
    async_requests: list[AsyncRequest] = relationship(
        "AsyncRequest", back_populates="project"
    )
    evaluation_results: list[EvaluationResult] = relationship(
        "EvaluationResult", back_populates="project"
    )


# ---------------------------------------------------------------------------
# questions
# ---------------------------------------------------------------------------
class Question(Base):
    __tablename__ = "questions"
    __allow_unmapped__ = True

    id = _uuid_pk()
    project_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    section_name = sa.Column(sa.Text, nullable=True)
    question_text = sa.Column(sa.Text, nullable=False)
    question_order = sa.Column(sa.Integer, nullable=True)
    question_number = sa.Column(sa.Integer, nullable=True)
    created_at = _now()

    # Relationships
    project: Project = relationship("Project", back_populates="questions")
    answers: list[Answer] = relationship(
        "Answer", back_populates="question", cascade="all, delete-orphan"
    )
    evaluation_results: list[EvaluationResult] = relationship(
        "EvaluationResult", back_populates="question"
    )


# ---------------------------------------------------------------------------
# answers
# ---------------------------------------------------------------------------
class Answer(Base):
    __tablename__ = "answers"
    __allow_unmapped__ = True

    id = _uuid_pk()
    question_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    # AI-generated answer — NEVER overwrite once set
    ai_answer_text = sa.Column(sa.Text, nullable=True)
    # Reviewer-authored answer (only when status=MANUAL_UPDATED)
    manual_answer_text = sa.Column(sa.Text, nullable=True)
    # The "active" answer shown to the user
    answer_text = sa.Column(sa.Text, nullable=True)
    can_answer = sa.Column(
        sa.Boolean, nullable=False, default=True, server_default="true"
    )
    confidence_score = sa.Column(
        sa.Float, nullable=False, default=0.0, server_default="0.0"
    )
    status = sa.Column(
        sa.Enum(AnswerStatus, name="answerstatus"),
        nullable=False,
        default=AnswerStatus.PENDING,
        server_default=AnswerStatus.PENDING.value,
    )
    reviewer_note = sa.Column(sa.Text, nullable=True)
    reviewed_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    created_at = _now()
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    # Relationships
    question: Question = relationship("Question", back_populates="answers")
    project: Project = relationship("Project", back_populates="answers")
    citations: list[Citation] = relationship(
        "Citation", back_populates="answer", cascade="all, delete-orphan"
    )
    audit_log: list[AnswerAuditLog] = relationship(
        "AnswerAuditLog", back_populates="answer", cascade="all, delete-orphan"
    )
    evaluation_results: list[EvaluationResult] = relationship(
        "EvaluationResult", back_populates="answer"
    )


# ---------------------------------------------------------------------------
# citations
# ---------------------------------------------------------------------------
class Citation(Base):
    __tablename__ = "citations"
    __allow_unmapped__ = True

    id = _uuid_pk()
    answer_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("answers.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    chunk_id = sa.Column(sa.Text, nullable=True)
    page_number = sa.Column(sa.Integer, nullable=True)
    excerpt_text = sa.Column(sa.Text, nullable=True)
    relevance_score = sa.Column(sa.Float, nullable=True)
    bounding_box = sa.Column(JSONB, nullable=True)
    created_at = _now()

    # Relationships
    answer: Answer = relationship("Answer", back_populates="citations")
    document: Document = relationship("Document", back_populates="citations")


# ---------------------------------------------------------------------------
# async_requests
# ---------------------------------------------------------------------------
class AsyncRequest(Base):
    __tablename__ = "async_requests"
    __allow_unmapped__ = True

    id = _uuid_pk()
    request_type = sa.Column(sa.Text, nullable=False)
    status = sa.Column(
        sa.Enum(RequestStatus, name="requeststatus"),
        nullable=False,
        default=RequestStatus.PENDING,
        server_default=RequestStatus.PENDING.value,
    )
    project_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_message = sa.Column(sa.Text, nullable=True)
    started_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    completed_at = sa.Column(sa.DateTime(timezone=True), nullable=True)
    created_at = _now()

    # Relationships
    project: Project = relationship("Project", back_populates="async_requests")


# ---------------------------------------------------------------------------
# evaluation_results
# ---------------------------------------------------------------------------
class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __allow_unmapped__ = True

    id = _uuid_pk()
    project_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    answer_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("answers.id", ondelete="CASCADE"),
        nullable=False,
    )
    human_answer_text = sa.Column(sa.Text, nullable=True)
    similarity_score = sa.Column(sa.Float, nullable=True)
    keyword_overlap = sa.Column(sa.Float, nullable=True)
    overall_score = sa.Column(sa.Float, nullable=True)
    explanation = sa.Column(sa.Text, nullable=True)
    created_at = _now()

    # Relationships
    project: Project = relationship("Project", back_populates="evaluation_results")
    question: Question = relationship("Question", back_populates="evaluation_results")
    answer: Answer = relationship("Answer", back_populates="evaluation_results")


# ---------------------------------------------------------------------------
# answer_audit_log
# ---------------------------------------------------------------------------
class AnswerAuditLog(Base):
    __tablename__ = "answer_audit_log"
    __allow_unmapped__ = True

    id = _uuid_pk()
    answer_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("answers.id", ondelete="CASCADE"),
        nullable=False,
    )
    old_status = sa.Column(sa.Text, nullable=True)
    new_status = sa.Column(sa.Text, nullable=True)
    changed_by = sa.Column(
        sa.Text, nullable=False, default="system", server_default="system"
    )
    change_note = sa.Column(sa.Text, nullable=True)
    changed_at = sa.Column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    # Relationships
    answer: Answer = relationship("Answer", back_populates="audit_log")
