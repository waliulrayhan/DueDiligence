"""Vercel entry point for the Questionnaire Agent API.

Vercel's filesystem is read-only except for /tmp, so we override UPLOAD_DIR
before any application module is imported (pydantic-settings reads env vars
at Settings() instantiation time, which happens at import of src.config).
"""

import os

# ---------------------------------------------------------------------------
# Environment patch – must happen before importing app or src.*
# ---------------------------------------------------------------------------
if os.environ.get("VERCEL"):
    # /tmp is the only writable directory on Vercel's Lambda runtime.
    # Force-override regardless of what's set in the Vercel dashboard —
    # setdefault() is insufficient because dashboard env vars are pre-loaded.
    os.environ["UPLOAD_DIR"] = "/tmp/uploads"
    os.makedirs("/tmp/uploads", exist_ok=True)

# ---------------------------------------------------------------------------
# Import the FastAPI application
# ---------------------------------------------------------------------------
# Importing app triggers src.config.settings instantiation, which will now
# see the patched UPLOAD_DIR when running on Vercel.
from app import app  # noqa: E402, F401  – re-exported for Vercel handler

# Vercel's @vercel/python runtime looks for a module-level ASGI callable
# named `app` (or the filename's implicit export).  The import above
# satisfies that requirement.
