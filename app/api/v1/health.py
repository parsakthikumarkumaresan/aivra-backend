from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.database.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def liveness() -> dict:
    """Process is up. Does not touch dependencies — used by orchestrator restarts."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(db: AsyncSession = Depends(get_db)) -> dict:
    """Process can actually serve traffic — verifies the database connection."""
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}
