from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger
from openai import OpenAI

from src.config import settings

# ---------------------------------------------------------------------------
# OpenAI-compatible client pointed at Groq
# ---------------------------------------------------------------------------
client = OpenAI(
    api_key=settings.groq_api_key,
    base_url=settings.groq_base_url,
)

_SYSTEM_PROMPT = (
    "You are a due diligence analyst reviewing investment documents.\n"
    "Answer questions using ONLY the provided document context.\n"
    "Always mention which document and page supports each point.\n"
    "If context only partially answers the question, say so explicitly."
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _build_context_string(chunks: list[dict[str, Any]]) -> str:
    """Format retrieved chunks into a readable context block for the prompt."""
    lines: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        doc_id = chunk.get("document_id", "unknown")
        page = chunk.get("page_number", "?")
        text = chunk.get("text", "").strip()
        lines.append(f"[{i}] Document: {doc_id} | Page: {page}\n{text}")
    return "\n\n---\n\n".join(lines)


def _build_citations(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": c.get("chunk_id", ""),
            "document_id": c.get("document_id", ""),
            "page_number": c.get("page_number", 0),
            "excerpt_text": c.get("text", ""),
            "relevance_score": c.get("relevance_score", 0.0),
        }
        for c in chunks
    ]


def _confidence_from_chunks(chunks: list[dict[str, Any]]) -> float:
    """Average relevance score of the top-3 chunks, clamped to [0, 1]."""
    top = chunks[:3]
    if not top:
        return 0.0
    scores = [float(c.get("relevance_score", 0.0)) for c in top]
    return round(min(max(sum(scores) / len(scores), 0.0), 1.0), 4)


# ---------------------------------------------------------------------------
# Public async interface
# ---------------------------------------------------------------------------

async def generate_answer(
    question: str,
    context_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate a grounded answer using the xAI Grok model.

    Parameters
    ----------
    question:
        The user's natural-language question.
    context_chunks:
        Retrieved chunks from the vector store.  Each dict should contain
        ``chunk_id``, ``document_id``, ``page_number``, ``text``,
        ``relevance_score``.

    Returns
    -------
    dict with keys:
        ``can_answer`` (bool), ``answer_text`` (str),
        ``confidence_score`` (float), ``citations`` (list) – present only
        when ``can_answer`` is True.
    """
    if not context_chunks:
        logger.debug("generate_answer: no context chunks – returning early.")
        return {
            "can_answer": False,
            "answer_text": "No relevant documents found.",
            "confidence_score": 0.0,
        }

    context_text = _build_context_string(context_chunks)
    user_message = (
        f"Context:\n{context_text}\n\n"
        f"Question: {question}"
    )

    logger.debug(
        "Calling {} with {} context chunks.", settings.llm_model, len(context_chunks)
    )

    # OpenAI SDK is synchronous; run it in a thread to avoid blocking the
    # asyncio event loop.
    def _call_api() -> str:
        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,  # low temperature for factual, deterministic answers
        )
        return response.choices[0].message.content or ""

    answer_text = await asyncio.to_thread(_call_api)

    confidence_score = _confidence_from_chunks(context_chunks)
    citations = _build_citations(context_chunks)

    logger.info(
        "Answer generated. confidence={:.4f}, citations={}",
        confidence_score,
        len(citations),
    )

    return {
        "can_answer": True,
        "answer_text": answer_text,
        "confidence_score": confidence_score,
        "citations": citations,
    }
