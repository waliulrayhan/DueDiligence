from __future__ import annotations

import uuid
import io

import PyPDF2
from docx import Document as DocxDocument


class DocumentParser:
    """Parse PDF / DOCX files into page dicts, then chunk them for indexing."""

    # ---------------------------------------------------------------------- #
    # Parsing                                                                  #
    # ---------------------------------------------------------------------- #

    def parse_pdf(self, file_path: str) -> list[dict]:
        """Return one dict per non-empty PDF page."""
        pages: list[dict] = []
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                text = (page.extract_text() or "").strip()
                if text:  # skip empty pages
                    pages.append({"page_number": i + 1, "text": text})
        return pages

    def parse_docx(self, file_path: str) -> list[dict]:
        """Group DOCX paragraphs into virtual pages of ~500 words."""
        doc = DocxDocument(file_path)
        pages: list[dict] = []
        current: list[str] = []
        word_count = 0

        for para in doc.paragraphs:
            stripped = para.text.strip()
            if stripped:
                current.append(stripped)
                word_count += len(stripped.split())
                if word_count >= 500:
                    pages.append(
                        {
                            "page_number": len(pages) + 1,
                            "text": " ".join(current),
                        }
                    )
                    current, word_count = [], 0

        if current:
            pages.append(
                {"page_number": len(pages) + 1, "text": " ".join(current)}
            )
        return pages

    def parse_file(self, file_path: str, file_type: str) -> list[dict]:
        """Dispatch to the correct parser based on *file_type* ('pdf'|'docx')."""
        if file_type == "pdf":
            return self.parse_pdf(file_path)
        elif file_type == "docx":
            return self.parse_docx(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")

    # ---------------------------------------------------------------------- #
    # Chunking                                                                 #
    # ---------------------------------------------------------------------- #

    def chunk_pages(
        self,
        pages: list[dict],
        chunk_size: int = 400,
        overlap: int = 80,
    ) -> list[dict]:
        """Split pages into overlapping word-based chunks.

        Each returned dict contains the keys expected by
        ``VectorStore.add_chunks``:
            - ``chunk_id``    – UUID string
            - ``text``        – chunk text
            - ``page_number`` – origin page (1-based)

        Plus two extra bookkeeping fields:
            - ``word_start``  – start word index within the page
            - ``word_end``    – end word index within the page
        """
        chunks: list[dict] = []
        for page in pages:
            words = page["text"].split()
            start = 0
            while start < len(words):
                end = min(start + chunk_size, len(words))
                chunk_text = " ".join(words[start:end])
                chunks.append(
                    {
                        "chunk_id": str(uuid.uuid4()),
                        "text": chunk_text,
                        "page_number": page["page_number"],
                        "word_start": start,
                        "word_end": end,
                    }
                )
                start += chunk_size - overlap
        return chunks


# ---------------------------------------------------------------------------
# Shared singleton
# ---------------------------------------------------------------------------
document_parser = DocumentParser()
