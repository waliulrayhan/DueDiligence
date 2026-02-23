"""
Utility script — wipe all application data from the database.

Usage (from backend folder with venv active):
  python reset_db.py

This is the fallback used by test_pipeline.py --reset when no
DELETE /api/admin/reset endpoint exists.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from src.storage.database import AsyncSessionLocal


_TABLES_IN_ORDER = [
    "answer_audit_log",
    "evaluation_results",
    "citations",
    "answers",
    "questions",
    "async_requests",
    "projects",
    "documents",
]


async def reset() -> None:
    async with AsyncSessionLocal() as db:
        for table in _TABLES_IN_ORDER:
            await db.execute(text(f"DELETE FROM {table}"))
            print(f"  Cleared table: {table}")
        await db.commit()
        print("  All tables cleared.")


if __name__ == "__main__":
    asyncio.run(reset())
