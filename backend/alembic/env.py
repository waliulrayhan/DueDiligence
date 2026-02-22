import sys
import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context

# ---------------------------------------------------------------------------
# Make sure `src` is importable when Alembic is run from the backend/ folder.
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
from src.config import settings  # noqa: E402
from src.models.db_models import Base  # noqa: E402  (registers all ORM models)

# ---------------------------------------------------------------------------
# Alembic config
# ---------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Tell autogenerate which metadata to compare against the live DB.
target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Build the sync connection URL for Alembic.
# We use settings.database_url_unpooled so Alembic gets a plain psycopg2
# URL (postgresql+psycopg2://...) rather than the asyncpg runtime URL.
# ---------------------------------------------------------------------------
def _get_alembic_url() -> str:
    url = settings.database_url_unpooled
    # Ensure the scheme is compatible with psycopg2 (sync driver).
    url = (
        url
        .replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
        .replace("postgresql://", "postgresql+psycopg2://", 1)
        .replace("postgres://", "postgresql+psycopg2://", 1)
    )
    return url


def run_migrations_offline() -> None:
    """Run migrations without an active DB connection (generates SQL script)."""
    url = _get_alembic_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    # Override sqlalchemy.url with the value from our settings so alembic.ini
    # does not need to contain credentials.
    config.set_main_option("sqlalchemy.url", _get_alembic_url())

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
