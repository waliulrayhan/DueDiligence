from contextlib import asynccontextmanager
from typing import AsyncGenerator
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from sqlalchemy import text

from src.config import settings
from src.indexing.vector_store import vector_store
from src.routers import answers, documents, evaluation, projects, requests
from src.storage.database import AsyncSessionLocal, create_all_tables


# ---------------------------------------------------------------------------
# Lifespan – startup & shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── startup ─────────────────────────────────────────────────────────────
    logger.info("Starting up Questionnaire Agent API…")

    # Ensure all SQLAlchemy-declared tables exist in the database.
    await create_all_tables()
    logger.info("Database tables verified/created.")

    # The VectorStore singleton is imported above; its __init__ already
    # called Pinecone and created the index if it was absent.  Log confirmation.
    logger.info(
        "Pinecone index '{}' ready.", settings.pinecone_index_name
    )

    yield  # ── application runs ────────────────────────────────────────────

    # ── shutdown ─────────────────────────────────────────────────────────────
    logger.info("Shutting down – releasing resources.")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Questionnaire Agent API",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# allow_origins covers the local Vite dev server (and any explicit deploy URL).
# allow_origin_regex covers all Vercel preview/production deployments.

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

API_PREFIX = "/api"

app.include_router(documents.router, prefix=API_PREFIX)
app.include_router(projects.router, prefix=API_PREFIX)
app.include_router(answers.router, prefix=API_PREFIX)
app.include_router(evaluation.router, prefix=API_PREFIX)
app.include_router(requests.router, prefix=API_PREFIX)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"])
async def health_check() -> dict:
    """Return liveness status plus connectivity checks for DB and Pinecone."""

    async def check_db() -> dict:
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
            return {"database": "ok"}
        except Exception as exc:
            logger.error("Health check – DB error: {}", exc)
            return {"database": "error"}

    async def check_pinecone() -> dict:
        try:
            # Pinecone SDK is synchronous – run in a thread to avoid blocking
            # the event loop while the HTTP round-trip completes.
            stats = await asyncio.to_thread(vector_store.get_stats)
            return {"pinecone": "ok", "pinecone_vector_count": stats.total_vector_count}
        except Exception as exc:
            logger.error("Health check – Pinecone error: {}", exc)
            return {"pinecone": "error"}

    # Run both checks concurrently instead of sequentially.
    db_result, pinecone_result = await asyncio.gather(check_db(), check_pinecone())

    health: dict = {"status": "ok", **db_result, **pinecone_result}
    if "error" in (db_result.get("database"), pinecone_result.get("pinecone")):
        health["status"] = "degraded"

    return health
