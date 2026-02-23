from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Database                                                             #
    # ------------------------------------------------------------------ #
    # Pooled connection string used by SQLAlchemy at runtime.
    # Example: postgresql+asyncpg://user:password@host:5432/dbname
    database_url: str

    # Unpooled connection string used by Alembic migrations (sync driver).
    # Example: postgresql+psycopg2://user:password@host:5432/dbname
    database_url_unpooled: str

    # ------------------------------------------------------------------ #
    # Pinecone vector store                                                #
    # ------------------------------------------------------------------ #
    pinecone_api_key: str
    pinecone_index_name: str
    pinecone_cloud: str   # e.g. "aws" or "gcp"
    pinecone_region: str  # e.g. "us-east-1"

    # ------------------------------------------------------------------ #
    # LLM (Groq / OpenAI-compatible)                                      #
    # ------------------------------------------------------------------ #
    groq_api_key: str
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "llama-3.3-70b-versatile"

    # ------------------------------------------------------------------ #
    # Application                                                          #
    # ------------------------------------------------------------------ #
    upload_dir: str = "./uploads"
    log_level: str = "INFO"
    frontend_url: str


# Single shared instance — import this everywhere:
#   from src.config import settings
settings = Settings()
