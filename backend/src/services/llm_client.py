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
    "You are a senior due diligence analyst reviewing investment documents.\n"
    "Answer the question using ONLY the provided document excerpts.\n"
    "Rules:\n"
    "- Always cite which document (filename) and page number supports each claim\n"
    "- If the context only partially answers, explicitly say: PARTIAL ANSWER\n"
    "- If context does not answer the question at all, say: CANNOT ANSWER\n"
    "- Keep your answer concise and factual\n"
    "- Format citations as [Source: filename, Page X]"
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _build_context_string(chunks: list[dict[str, Any]]) -> str:
    """Format retrieved chunks into a readable context block for the prompt.

    Uses ``document_filename`` (attached by retrieval_service) when available,
    falling back to ``document_id`` so the prompt always has a source label.
    """
    parts: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        filename = chunk.get("document_filename") or chunk.get("document_id", "unknown")
        page = chunk.get("page_number", "?")
        text = chunk.get("text", "").strip()
        parts.append(
            f"[Excerpt {i}] Source: {filename}, Page {page}\n{text}"
        )
    return "\n\n---\n\n".join(parts)


def _build_citations(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build citation dicts; excerpt_text is capped at 400 chars."""
    return [
        {
            "chunk_id": c.get("chunk_id", ""),
            "document_id": c.get("document_id", ""),
            "page_number": c.get("page_number", 0),
            "excerpt_text": c.get("text", "")[:400],
            "relevance_score": c.get("relevance_score", 0.0),
        }
        for c in chunks
    ]


def _confidence_from_chunks(
    chunks: list[dict[str, Any]],
    *,
    is_partial: bool = False,
    can_answer: bool = True,
) -> float:
    """Derive confidence from the top-3 relevance scores.

    Applies a 0.75 penalty for partial answers and returns 0.0 when the
    model signals it cannot answer at all.
    """
    if not can_answer:
        return 0.0
    top_scores = sorted(
        [float(c.get("relevance_score", 0.0)) for c in chunks], reverse=True
    )[:3]
    if not top_scores:
        return 0.0
    base = sum(top_scores) / len(top_scores)
    if is_partial:
        base *= 0.75
    return min(round(base, 3), 1.0)


# ---------------------------------------------------------------------------
# Public async interface
# ---------------------------------------------------------------------------

async def generate_answer(
    question: str,
    context_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate a grounded answer using the Groq LLM (OpenAI-compatible).

    Parameters
    ----------
    question:
        The user's natural-language question.
    context_chunks:
        Retrieved chunks from the vector store.  Each dict should contain
        ``chunk_id``, ``document_id``, ``document_filename``, ``page_number``,
        ``text``, ``relevance_score``.

    Returns
    -------
    dict with keys:
        ``can_answer`` (bool), ``answer_text`` (str),
        ``confidence_score`` (float), ``citations`` (list).
    """
    if not context_chunks:
        logger.debug("generate_answer: no context chunks – returning early.")
        return {
            "can_answer": False,
            "answer_text": "No relevant information found in the indexed documents.",
            "confidence_score": 0.0,
            "citations": [],
        }

    context_text = _build_context_string(context_chunks)
    user_message = (
        f"QUESTION: {question}\n\n"
        f"DOCUMENT CONTEXT:\n{context_text}"
    )

    logger.debug(
        "Calling {} with {} context chunks.", settings.llm_model, len(context_chunks)
    )

    # OpenAI SDK is synchronous; run it in a thread to avoid blocking the
    # asyncio event loop.
    def _call_groq() -> str:
        response = client.chat.completions.create(
            model=settings.llm_model,  # e.g. llama-3.3-70b-versatile
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=800,
            temperature=0.1,
        )
        return response.choices[0].message.content or ""

    answer_text = await asyncio.to_thread(_call_groq)

    can_answer = "CANNOT ANSWER" not in answer_text
    is_partial = "PARTIAL ANSWER" in answer_text

    confidence_score = _confidence_from_chunks(
        context_chunks, is_partial=is_partial, can_answer=can_answer
    )
    citations = _build_citations(context_chunks)

    logger.info(
        "Answer generated. can_answer={} partial={} confidence={:.3f} citations={}",
        can_answer,
        is_partial,
        confidence_score,
        len(citations),
    )

    return {
        "can_answer": can_answer,
        "answer_text": answer_text,
        "confidence_score": confidence_score,
        "citations": citations,
    }
