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
_EMBED_MODEL = "all-MiniLM-L6-v2"
_DIMENSION = 384
_METRIC = "cosine"


class VectorStore:
    """Thin wrapper around Pinecone that handles embedding + upsert / query."""

    def __init__(self) -> None:
        # ── Pinecone client ────────────────────────────────────────────────
        self._pc = Pinecone(api_key=settings.pinecone_api_key)
        self._index_name = settings.pinecone_index_name

        existing = [idx.name for idx in self._pc.list_indexes()]
        if self._index_name not in existing:
            logger.info(
                "Pinecone index '{}' not found – creating it "
                "(cloud={}, region={}).",
                self._index_name,
                settings.pinecone_cloud,
                settings.pinecone_region,
            )
            self._pc.create_index(
                name=self._index_name,
                dimension=_DIMENSION,
                metric=_METRIC,
                spec=ServerlessSpec(
                    cloud=settings.pinecone_cloud,
                    region=settings.pinecone_region,
                ),
            )
            logger.info("Index '{}' created.", self._index_name)
        else:
            logger.debug("Using existing Pinecone index '{}'.", self._index_name)

        self._index = self._pc.Index(self._index_name)

        # ── Embedding model ────────────────────────────────────────────────
        logger.debug("Loading sentence-transformer model '{}'.", _EMBED_MODEL)
        self._embedder = SentenceTransformer(_EMBED_MODEL)

    # ---------------------------------------------------------------------- #
    # Public API                                                               #
    # ---------------------------------------------------------------------- #

    def add_chunks(
        self,
        document_id: str,
        chunks: list[dict[str, Any]],
    ) -> None:
        """Embed *chunks* and upsert them into Pinecone.

        Each item in *chunks* must have:
            - ``chunk_id``    (str)  unique identifier for this chunk
            - ``text``        (str)  raw text to embed
            - ``page_number`` (int)  origin page (1-based; 0 if unknown)

        Additional keys are ignored.
        """
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        embeddings = self._embedder.encode(texts, show_progress_bar=False).tolist()

        vectors = [
            {
                "id": chunk["chunk_id"],
                "values": embedding,
                "metadata": {
                    "document_id": document_id,
                    "chunk_id": chunk["chunk_id"],
                    "page_number": chunk.get("page_number", 0),
                    "text": chunk["text"],
                },
            }
            for chunk, embedding in zip(chunks, embeddings)
        ]

        # Pinecone recommends batches of ≤100 vectors per upsert call.
        batch_size = 100
        for start in range(0, len(vectors), batch_size):
            batch = vectors[start : start + batch_size]
            self._index.upsert(vectors=batch)

        logger.info(
            "Upserted {} chunks for document '{}'.", len(vectors), document_id
        )

    def search(
        self,
        query_text: str,
        n_results: int = 5,
        filter_document_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Embed *query_text* and return the top *n_results* matching chunks.

        Returns a list of dicts with keys:
            ``chunk_id``, ``document_id``, ``text``, ``page_number``,
            ``relevance_score``
        """
        query_vector = self._embedder.encode(
            query_text, show_progress_bar=False
        ).tolist()

        pinecone_filter: dict[str, Any] | None = None
        if filter_document_ids:
            pinecone_filter = {"document_id": {"$in": filter_document_ids}}

        response = self._index.query(
            vector=query_vector,
            top_k=n_results,
            include_metadata=True,
            filter=pinecone_filter,
        )

        results: list[dict[str, Any]] = []
        for match in response.matches:
            meta = match.metadata or {}
            results.append(
                {
                    "chunk_id": meta.get("chunk_id", match.id),
                    "document_id": meta.get("document_id", ""),
                    "text": meta.get("text", ""),
                    "page_number": meta.get("page_number", 0),
                    "relevance_score": match.score,
                }
            )

        return results

    def delete_document_chunks(self, document_id: str) -> None:
        """Delete all vectors whose metadata.document_id matches *document_id*.

        Pinecone serverless supports metadata-filtered deletes via
        ``delete(filter=...)``.
        """
        self._index.delete(filter={"document_id": {"$eq": document_id}})
        logger.info(
            "Deleted all chunks for document '{}' from Pinecone.", document_id
        )


# ---------------------------------------------------------------------------
# Shared singleton – import this everywhere:
#   from src.indexing.vector_store import vector_store
# ---------------------------------------------------------------------------
vector_store = VectorStore()
