from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models.session import RefreshToken, Session
from app.shared.security.hashing import hash_token


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_session(self, entity: Session) -> Session:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def get_session(self, session_id: str) -> Session | None:
        return await self.session.get(Session, session_id)

    async def add_refresh_token(self, entity: RefreshToken) -> RefreshToken:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def get_refresh_token_by_raw(self, raw_token: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_session_family(self, session_id: str) -> None:
        """Revoke the session and all its refresh tokens — used on logout or reuse detection."""
        now = datetime.now(UTC)
        session_row = await self.get_session(session_id)
        if session_row and session_row.revoked_at is None:
            session_row.revoked_at = now

        stmt = select(RefreshToken).where(
            RefreshToken.session_id == session_id, RefreshToken.revoked_at.is_(None)
        )
        result = await self.session.execute(stmt)
        for token in result.scalars().all():
            token.revoked_at = now
