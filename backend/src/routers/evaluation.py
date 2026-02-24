"""Evaluation router — run evaluation and retrieve reports.

POST /evaluation          — score AI answers against human ground truth
GET  /evaluation/{id}    — retrieve the latest evaluation report for a project
"""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db_models import Answer, EvaluationResult, Project, Question
from src.models.schemas import EvaluateRequest
from src.storage.database import get_db

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into words."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _cosine_similarity(a: str, b: str) -> float:
    """TF-vector cosine similarity between two strings."""
    if not a or not b:
        return 0.0
    va = Counter(_tokenize(a))
    vb = Counter(_tokenize(b))
    keys = set(va) | set(vb)
    dot = sum(va[k] * vb[k] for k in keys)
    mag_a = math.sqrt(sum(v * v for v in va.values()))
    mag_b = math.sqrt(sum(v * v for v in vb.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _keyword_overlap(a: str, b: str) -> float:
    """Jaccard similarity of word sets (ignoring stop-words)."""
    STOP = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "and", "or", "but", "not", "it", "its", "this", "that", "i"}
    sa = {w for w in _tokenize(a) if w not in STOP}
    sb = {w for w in _tokenize(b) if w not in STOP}
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _score(ai: str, human: str) -> dict[str, Any]:
    sim = round(_cosine_similarity(ai, human), 4)
    kwov = round(_keyword_overlap(ai, human), 4)
    overall = round((sim + kwov) / 2, 4)

    if overall >= 0.8:
        tag = "Strong semantic and keyword alignment."
    elif overall >= 0.6:
        tag = "Good alignment with minor gaps."
    elif overall >= 0.4:
        tag = "Partial overlap; some key points missing."
    else:
        tag = "Low similarity; answers diverge significantly."

    return {
        "similarity_score": sim,
        "keyword_overlap": kwov,
        "overall_score": overall,
        "explanation": tag,
    }


# ---------------------------------------------------------------------------
# POST /evaluation  — run evaluation
# ---------------------------------------------------------------------------

@router.post("")
async def run_evaluation(
    body: EvaluateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Score each AI answer against the supplied human ground truth."""

    project = await db.get(Project, uuid.UUID(body.project_id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    if not body.ground_truth:
        raise HTTPException(status_code=422, detail="ground_truth list is empty.")

    results: list[dict[str, Any]] = []

    for item in body.ground_truth:
        try:
            q_uuid = uuid.UUID(item.question_id)
        except ValueError:
            continue

        question = await db.get(Question, q_uuid)
        if not question or str(question.project_id) != body.project_id:
            logger.warning("Evaluation: question {} not found for project {}", item.question_id, body.project_id)
            continue

        ans_q = await db.execute(
            select(Answer).where(
                Answer.question_id == str(q_uuid),
                Answer.project_id == body.project_id,
            )
        )
        answer = ans_q.scalar_one_or_none()
        if not answer or not answer.answer_text:
            logger.warning("Evaluation: no answer for question {} — skipping", item.question_id)
            continue

        scored = _score(answer.answer_text, item.human_answer_text)

        # Upsert: delete old result for this question, then insert fresh one
        await db.execute(
            delete(EvaluationResult).where(
                EvaluationResult.project_id == uuid.UUID(body.project_id),
                EvaluationResult.question_id == q_uuid,
            )
        )
        db.add(EvaluationResult(
            project_id=uuid.UUID(body.project_id),
            question_id=q_uuid,
            answer_id=answer.id,
            human_answer_text=item.human_answer_text,
            **scored,
        ))

        results.append({
            "question_id": item.question_id,
            "question_text": question.question_text,
            "ai_answer_text": answer.answer_text,
            "human_answer_text": item.human_answer_text,
            **scored,
        })

    await db.commit()

    logger.info(
        "Evaluation complete: project={} scored={}/{} items",
        body.project_id, len(results), len(body.ground_truth),
    )

    return _build_report(results)


# ---------------------------------------------------------------------------
# GET /evaluation/{project_id}  — retrieve saved report
# ---------------------------------------------------------------------------

@router.get("/{project_id}")
async def get_evaluation_report(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the most recent saved evaluation results for a project."""

    try:
        p_uuid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project_id UUID.")

    project = await db.get(Project, p_uuid)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    rows_q = await db.execute(
        select(EvaluationResult, Question)
        .join(Question, EvaluationResult.question_id == Question.id)
        .where(EvaluationResult.project_id == p_uuid)
        .order_by(Question.question_order.asc().nullslast())
    )

    results: list[dict[str, Any]] = []
    for ev, q in rows_q.all():
        # Re-fetch current AI answer text
        ans_q = await db.execute(
            select(Answer.answer_text).where(Answer.id == ev.answer_id)
        )
        ai_text = ans_q.scalar_one_or_none()

        results.append({
            "question_id": str(ev.question_id),
            "question_text": q.question_text,
            "ai_answer_text": ai_text,
            "human_answer_text": ev.human_answer_text,
            "overall_score": ev.overall_score or 0.0,
            "similarity_score": ev.similarity_score or 0.0,
            "keyword_overlap": ev.keyword_overlap or 0.0,
            "explanation": ev.explanation,
        })

    return _build_report(results)


# ---------------------------------------------------------------------------
# Shared report builder
# ---------------------------------------------------------------------------

def _build_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {"aggregates": {"avg_score": 0, "count_excellent": 0, "count_good": 0, "count_poor": 0, "total": 0}, "results": []}

    scores = [r["overall_score"] for r in results]
    avg = round(sum(scores) / len(scores), 4)
    excellent = sum(1 for s in scores if s >= 0.8)
    good = sum(1 for s in scores if 0.6 <= s < 0.8)
    poor = sum(1 for s in scores if s < 0.4)

    return {
        "aggregates": {
            "avg_score": avg,
            "count_excellent": excellent,
            "count_good": good,
            "count_poor": poor,
            "total": len(results),
        },
        "results": results,
    }

