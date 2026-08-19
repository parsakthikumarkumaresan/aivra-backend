from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.leads.models.requirement import Requirement
from app.leads.models.voice_project import VoiceProject


class VoiceProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, project: VoiceProject) -> VoiceProject:
        self.session.add(project)
        await self.session.flush()
        return project

    async def get_by_id(self, project_id: str) -> VoiceProject | None:
        return await self.session.get(VoiceProject, project_id)

    async def list_all(self) -> list[VoiceProject]:
        stmt = select(VoiceProject).order_by(VoiceProject.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_organization(self, organization_id: str) -> list[VoiceProject]:
        stmt = select(VoiceProject).where(VoiceProject.organization_id == organization_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_requirement(self, requirement: Requirement) -> Requirement:
        self.session.add(requirement)
        await self.session.flush()
        return requirement

    async def list_requirements(self, project_id: str) -> list[Requirement]:
        stmt = select(Requirement).where(Requirement.voice_project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
