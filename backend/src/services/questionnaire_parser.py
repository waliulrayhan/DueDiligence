from __future__ import annotations

import re
from typing import TypedDict

from loguru import logger


# ---------------------------------------------------------------------------
# Typed output matching the Question DB model fields
# ---------------------------------------------------------------------------

class ParsedQuestion(TypedDict):
    section_name: str
    question_text: str
    question_order: int
    question_number: int


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class QuestionnaireParser:
    """Parse a questionnaire PDF into a flat list of question dicts.

    Each returned dict maps directly onto the ``Question`` DB model columns:
        - ``section_name``    – heading under which the question appears
        - ``question_text``   – raw question text
        - ``question_order``  – global 1-based ordinal across the whole file
        - ``question_number`` – 1-based ordinal within the current section

    Supports ILPA DDQ layout where sections use Roman-numeral prefixes
    (e.g. "I. FIRM OVERVIEW") and questions are numbered items or sentences
    ending with "?".
    """

    # Section-header patterns (evaluated in order; first match wins)
    SECTION_PATTERNS: list[str] = [
        r"^[IVX]+\.\s+[A-Z]",           # Roman numerals:  I. FIRM OVERVIEW
        r"^\d+\.\s+[A-Z][A-Z\s]{5,}",   # Numbered:        1. FIRM OVERVIEW
        r"^[A-Z][A-Z\s]{8,}$",           # ALL-CAPS header: FIRM OVERVIEW
    ]

    # Question-line patterns (case-insensitive; any match qualifies)
    QUESTION_PATTERNS: list[str] = [
        r".*\?$",                          # ends with ?
        r"^(Please|Provide|Describe|Explain|List|What|How|When|Where|Who|Is|Are|Does)",
        r"^\d+\.\d+",                      # sub-numbered items: 1.1, 2.3
    ]

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    def parse(self, file_path: str) -> list[ParsedQuestion]:
        """Extract questions from *file_path* (PDF).

        Parameters
        ----------
        file_path:
            Absolute or workspace-relative path to the questionnaire PDF.

        Returns
        -------
        list[ParsedQuestion]
            Ordered list of question dicts ready to be inserted as ``Question``
            rows.  Falls back to sentence splitting when fewer than 5 entries
            are detected via the normal heuristics.
        """
        logger.info("QuestionnaireParser: reading '{}'", file_path)
        all_text = self._extract_text(file_path)
        questions = self._extract_questions(all_text)

        if len(questions) < 5:
            logger.warning(
                "QuestionnaireParser: only {} questions detected via patterns — "
                "falling back to sentence splitting.",
                len(questions),
            )
            questions = self._sentence_fallback(all_text)

        logger.info(
            "QuestionnaireParser: extracted {} questions from '{}'.",
            len(questions),
            file_path,
        )
        return questions

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _extract_text(self, file_path: str) -> str:
        """Read all pages from a PDF and return concatenated text."""
        import PyPDF2  # lazy import — only required for this service

        all_text = ""
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                all_text += (page.extract_text() or "") + "\n"
        return all_text

    def _extract_questions(self, all_text: str) -> list[ParsedQuestion]:
        """Apply section and question patterns to *all_text*."""
        lines = [line.strip() for line in all_text.split("\n") if line.strip()]

        questions: list[ParsedQuestion] = []
        current_section = "General"
        q_order = 0
        q_num_in_section = 0

        for line in lines:
            # ── Section header detection ───────────────────────────────────
            is_section = any(
                re.match(pattern, line)
                for pattern in self.SECTION_PATTERNS
            )
            # Guard: headers are short; very long matches are likely body text
            if is_section and len(line) < 120:
                current_section = line.title()
                q_num_in_section = 0
                continue

            # ── Question detection ─────────────────────────────────────────
            is_question = any(
                re.match(pattern, line, re.IGNORECASE)
                for pattern in self.QUESTION_PATTERNS
            )
            # Guard: ignore very short matches (e.g. bare "Is" or "Are")
            if is_question and len(line) > 20:
                q_order += 1
                q_num_in_section += 1
                questions.append(
                    ParsedQuestion(
                        section_name=current_section,
                        question_text=line,
                        question_order=q_order,
                        question_number=q_num_in_section,
                    )
                )

        return questions

    def _sentence_fallback(self, all_text: str) -> list[ParsedQuestion]:
        """Split *all_text* by period and treat each sentence as a question.

        Used only when the pattern-based approach finds fewer than 5 results
        (e.g. scanned/image PDFs where ``extract_text`` returns minimal text).
        Capped at 50 entries to avoid noise.
        """
        sentences = [s.strip() for s in all_text.split(".") if len(s.strip()) > 40]
        return [
            ParsedQuestion(
                section_name="General",
                question_text=sentence + ".",
                question_order=i + 1,
                question_number=i + 1,
            )
            for i, sentence in enumerate(sentences[:50])
        ]


# ---------------------------------------------------------------------------
# Module-level singleton (mirrors the ``document_parser`` pattern)
# ---------------------------------------------------------------------------

questionnaire_parser = QuestionnaireParser()
