from __future__ import annotations

from typing import Any

from loguru import logger
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer

from src.config import settings

# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------
# all-MiniLM-L6-v2 produces 384-dimensional vectors and is fast enough to run
# on CPU.  The model is downloaded once on first use and cached locally.
# Index name is configured via PINECONE_INDEX_NAME env var (default: 'duediligence-chunks').
_EMBED_MODEL = "all-MiniLM-L6-v2"
_DIMENSION = 384
_METRIC = "cosine"


class VectorStore:
    """Thin wrapper around Pinecone that handles embedding + upsert / query."""

    def __init__(self) -> None:
        # ── Pinecone client ────────────────────────────────────────────────
        self.pc = Pinecone(api_key=settings.pinecone_api_key)
        self.index_name = settings.pinecone_index_name  # e.g. 'duediligence-chunks'

        existing = [idx.name for idx in self.pc.list_indexes()]
        if self.index_name not in existing:
            logger.info(
                "Pinecone index '{}' not found – creating it "
                "(cloud={}, region={}).",
                self.index_name,
                settings.pinecone_cloud,
                settings.pinecone_region,
            )
            self.pc.create_index(
                name=self.index_name,
                dimension=_DIMENSION,
                metric=_METRIC,
                spec=ServerlessSpec(
                    cloud=settings.pinecone_cloud,
                    region=settings.pinecone_region,
                ),
            )
            logger.info("Index '{}' created.", self.index_name)
        else:
            logger.debug("Using existing Pinecone index '{}'.", self.index_name)

        self.index = self.pc.Index(self.index_name)

        # ── Embedding model ────────────────────────────────────────────────
        logger.debug("Loading sentence-transformer model '{}'.", _EMBED_MODEL)
        self.model = SentenceTransformer(_EMBED_MODEL)

    # ---------------------------------------------------------------------- #
    # Public API                                                               #
    # ---------------------------------------------------------------------- #

    def add_chunks(self, document_id: str, chunks: list[dict[str, Any]]) -> None:
        """Embed *chunks* and upsert them into Pinecone.

        Each item in *chunks* must have:
            - ``chunk_id``    (str)  unique identifier for this chunk
            - ``text``        (str)  raw text to embed
            - ``page_number`` (int)  origin page (1-based; 0 if unknown)

        Optional keys stored in metadata when present:
            - ``word_start`` / ``word_end``  – word-offset bookmarks from the parser
        """
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        embeddings = self.model.encode(
            texts, batch_size=32, show_progress_bar=False
        ).tolist()

        vectors: list[dict[str, Any]] = []
        for chunk, embedding in zip(chunks, embeddings):
            metadata: dict[str, Any] = {
                "document_id": document_id,
                "chunk_id": chunk["chunk_id"],
                "page_number": chunk.get("page_number", 0),
                # Truncate to stay within Pinecone's metadata size limit
                "text": chunk["text"][:1000],
            }
            # Persist word offsets produced by DocumentParser.chunk_pages
            if "word_start" in chunk:
                metadata["word_start"] = chunk["word_start"]
            if "word_end" in chunk:
                metadata["word_end"] = chunk["word_end"]

            vectors.append(
                {
                    "id": chunk["chunk_id"],
                    "values": embedding,
                    "metadata": metadata,
                }
            )

        # Pinecone recommends batches of ≤100 vectors per upsert call.
        for i in range(0, len(vectors), 100):
            self.index.upsert(vectors=vectors[i : i + 100])

        logger.info(
            "Upserted {} chunks for document '{}'.", len(vectors), document_id
        )

    def search(
        self,
        query: str,
        n_results: int = 8,
        filter_document_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Embed *query* and return the top *n_results* matching chunks.

        Returns a list of dicts with keys:
            ``chunk_id``, ``document_id``, ``text``, ``page_number``,
            ``relevance_score``
        """
        query_embedding = self.model.encode(
            [query], show_progress_bar=False
        ).tolist()[0]

        pinecone_filter: dict[str, Any] | None = None
        if filter_document_ids:
            pinecone_filter = {"document_id": {"$in": filter_document_ids}}

        response = self.index.query(
            vector=query_embedding,
            top_k=n_results,
            filter=pinecone_filter,
            include_metadata=True,
        )

        return [
            {
                "chunk_id": m.id,
                "document_id": (m.metadata or {}).get("document_id", ""),
                "text": (m.metadata or {}).get("text", ""),
                "page_number": (m.metadata or {}).get("page_number", 0),
                "relevance_score": float(m.score),
            }
            for m in response.matches
        ]

    def delete_document(self, document_id: str) -> None:
        """Delete all vectors whose metadata.document_id matches *document_id*."""
        self.index.delete(filter={"document_id": {"$eq": document_id}})
        logger.info(
            "Deleted all chunks for document '{}' from Pinecone.", document_id
        )

    def get_stats(self) -> dict[str, Any]:
        """Return index statistics from Pinecone (vector count, dimension, etc.)."""
        return self.index.describe_index_stats()


# ---------------------------------------------------------------------------
# Shared singleton – import this everywhere:
#   from src.indexing.vector_store import vector_store
# ---------------------------------------------------------------------------
vector_store = VectorStore()
