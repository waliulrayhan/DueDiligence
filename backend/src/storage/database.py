from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

from src.config import settings

# ---------------------------------------------------------------------------
# Connection URL
# ---------------------------------------------------------------------------
# 1. Normalise the scheme to postgresql+asyncpg (Neon gives plain postgresql://)
# 2. Replace ?sslmode=require with ?ssl=require – asyncpg does not understand
#    the libpq/psycopg2 `sslmode` parameter and raises a TypeError if it is
#    present.  The equivalent asyncpg parameter is just `ssl`.
_db_url = (
    settings.database_url
    .replace("postgresql://", "postgresql+asyncpg://", 1)
    .replace("postgres://", "postgresql+asyncpg://", 1)
    .replace("sslmode=require", "ssl=require")
    .replace("sslmode=verify-full", "ssl=verify-full")
    .replace("sslmode=disable", "ssl=disable")
)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# NullPool is required for serverless runtimes (Neon on Vercel / AWS Lambda):
# each request opens and closes its own connection rather than holding one in
# a pool between invocations, which would time-out on cold starts.
engine = create_async_engine(
    _db_url,
    poolclass=NullPool,
    echo=settings.log_level.upper() == "DEBUG",  # SQL logging in debug mode
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # avoid lazy-load errors after commit
    autoflush=False,
    autocommit=False,
)

# ---------------------------------------------------------------------------
# Declarative base – import this in every model file:
#   from src.storage.database import Base
# ---------------------------------------------------------------------------
Base = declarative_base()


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession and guarantee it is closed after the request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Table creation helper (called once at startup for dev / CI)
# ---------------------------------------------------------------------------
async def create_all_tables() -> None:
    """Create all tables registered on Base.metadata (dev / smoke-test use).

    For production schema changes use Alembic migrations instead.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
