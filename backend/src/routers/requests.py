from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db_models import AsyncRequest
from src.models.schemas import AsyncRequestResponse
from src.storage.database import get_db

router = APIRouter(prefix="/requests", tags=["requests"])


@router.get("/{request_id}", response_model=AsyncRequestResponse)
async def get_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
) -> AsyncRequestResponse:
    """Poll the status of an async operation by its request ID."""
    req = await db.get(AsyncRequest, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found.")

    return AsyncRequestResponse(
        request_id=str(req.id),
        status=req.status,
        error_message=req.error_message,
        completed_at=req.completed_at,
    )
