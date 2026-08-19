"""Voice Agent Builder: identity + versioned configuration lifecycle (spec
sections 10.1, 20; ADR 0003).

``update_draft`` implements the frontend's ``updateVoiceAgent(id, patch)``
contract for real — it shallow-merges section patches into the current
DRAFT version and is the only mutable point in the whole version history;
everything from TEST onward is append-only.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ai_employees.voice.models.agent_version import (
    AGENT_VERSION_TRANSITIONS,
    AgentVersion,
    AgentVersionStatus,
)
from app.ai_employees.voice.models.voice_agent import VoiceAgent, VoiceAgentStatus
from app.ai_employees.voice.repositories.agent_version_repository import AgentVersionRepository
from app.ai_employees.voice.repositories.voice_agent_repository import VoiceAgentRepository
from app.shared.errors.exceptions import ConflictError, NotFoundError, ValidationAppError

_CONFIG_SECTIONS = (
    "prompt_config",
    "flow_config",
    "context_config",
    "library",
    "tool_ids",
    "voice_config",
    "transcription_config",
    "call_end_config",
    "transfer_config",
    "analysis_config",
    "call_actions_config",
    "advanced_config",
)


def _copy_config_sections(source: AgentVersion) -> dict:
    return {section: getattr(source, section) for section in _CONFIG_SECTIONS}


class VoiceAgentService:
    def __init__(
        self, agent_repo: VoiceAgentRepository, version_repo: AgentVersionRepository
    ) -> None:
        self.agent_repo = agent_repo
        self.version_repo = version_repo

    async def list_agents(self, organization_id: str) -> list[VoiceAgent]:
        return await self.agent_repo.list_for_organization(organization_id)

    async def get_agent(self, organization_id: str, agent_id: str) -> VoiceAgent:
        agent = await self.agent_repo.get_by_id(organization_id, agent_id)
        if agent is None:
            raise NotFoundError("Voice agent not found.")
        return agent

    async def create_agent(
        self, *, organization_id: str, created_by_user_id: str, name: str, industry: str | None
    ) -> tuple[VoiceAgent, AgentVersion]:
        agent = await self.agent_repo.add(
            VoiceAgent(organization_id=organization_id, name=name, industry=industry)
        )
        draft = await self.version_repo.add(
            AgentVersion(
                organization_id=organization_id,
                voice_agent_id=agent.id,
                version_number=1,
                status=AgentVersionStatus.DRAFT,
                created_by_user_id=created_by_user_id,
            )
        )
        return agent, draft

    async def get_draft(self, organization_id: str, agent_id: str) -> AgentVersion:
        draft = await self.version_repo.get_draft(organization_id, agent_id)
        if draft is None:
            raise NotFoundError("This agent has no editable draft version.")
        return draft

    async def get_active_version(self, organization_id: str, agent_id: str) -> AgentVersion | None:
        return await self.version_repo.get_active_published(organization_id, agent_id)

    async def list_versions(self, organization_id: str, agent_id: str) -> list[AgentVersion]:
        return await self.version_repo.list_for_agent(organization_id, agent_id)

    async def update_draft(
        self, organization_id: str, agent_id: str, *, patch: dict
    ) -> AgentVersion:
        draft = await self.get_draft(organization_id, agent_id)
        camel_map = {
            "promptConfig": "prompt_config",
            "flowConfig": "flow_config",
            "contextConfig": "context_config",
            "toolIds": "tool_ids",
            "voiceConfig": "voice_config",
            "transcriptionConfig": "transcription_config",
            "callEndConfig": "call_end_config",
            "transferConfig": "transfer_config",
            "analysisConfig": "analysis_config",
            "callActionsConfig": "call_actions_config",
            "advancedConfig": "advanced_config",
        }
        for section, value in patch.items():
            norm_section = camel_map.get(section, section)
            if norm_section not in _CONFIG_SECTIONS:
                raise ValidationAppError(f"Unknown config section: {section!r}")
            setattr(draft, norm_section, value)
        return draft

    async def submit_for_test(self, organization_id: str, agent_id: str) -> AgentVersion:
        draft = await self.get_draft(organization_id, agent_id)
        AGENT_VERSION_TRANSITIONS.assert_transition_allowed(draft.status, AgentVersionStatus.TEST)
        draft.status = AgentVersionStatus.TEST
        agent = await self.get_agent(organization_id, agent_id)
        agent.status = VoiceAgentStatus.TESTING
        return draft

    async def send_back_to_draft(self, organization_id: str, agent_id: str) -> AgentVersion:
        """From TEST or APPROVED back to DRAFT — e.g. testing surfaced an
        issue that needs another edit before re-submitting.
        """
        version = await self._get_editable_version(organization_id, agent_id)
        AGENT_VERSION_TRANSITIONS.assert_transition_allowed(
            version.status, AgentVersionStatus.DRAFT
        )
        version.status = AgentVersionStatus.DRAFT
        return version

    async def approve(self, organization_id: str, agent_id: str) -> AgentVersion:
        version = await self._require_version_in_status(
            organization_id, agent_id, AgentVersionStatus.TEST
        )
        AGENT_VERSION_TRANSITIONS.assert_transition_allowed(
            version.status, AgentVersionStatus.APPROVED
        )
        version.status = AgentVersionStatus.APPROVED
        return version

    async def publish(self, organization_id: str, agent_id: str) -> AgentVersion:
        version = await self._require_version_in_status(
            organization_id, agent_id, AgentVersionStatus.APPROVED
        )
        AGENT_VERSION_TRANSITIONS.assert_transition_allowed(
            version.status, AgentVersionStatus.PUBLISHED
        )
        await self._archive_current_active(organization_id, agent_id)

        version.status = AgentVersionStatus.PUBLISHED
        version.is_active = True
        version.published_at = datetime.now(UTC)

        agent = await self.get_agent(organization_id, agent_id)
        agent.status = VoiceAgentStatus.LIVE

        # Editing must always have somewhere to go — open a fresh draft
        # copying what was just published.
        await self._open_new_draft(organization_id, agent, version)
        return version

    async def rollback(
        self, organization_id: str, agent_id: str, *, target_version_id: str
    ) -> AgentVersion:
        target = await self.version_repo.get_by_id(organization_id, target_version_id)
        if target is None or target.voice_agent_id != agent_id:
            raise NotFoundError("Target version not found for this agent.")
        if target.status not in (AgentVersionStatus.PUBLISHED, AgentVersionStatus.ARCHIVED):
            raise ConflictError("Can only roll back to a previously published version.")

        await self._archive_current_active(organization_id, agent_id)

        next_number = (
            await self.version_repo.get_latest_version_number(organization_id, agent_id) + 1
        )
        rolled_back = await self.version_repo.add(
            AgentVersion(
                organization_id=organization_id,
                voice_agent_id=agent_id,
                version_number=next_number,
                status=AgentVersionStatus.PUBLISHED,
                is_active=True,
                published_at=datetime.now(UTC),
                created_by_user_id=target.created_by_user_id,
                **_copy_config_sections(target),
            )
        )
        agent = await self.get_agent(organization_id, agent_id)
        agent.status = VoiceAgentStatus.LIVE
        return rolled_back

    async def pause(self, organization_id: str, agent_id: str) -> VoiceAgent:
        agent = await self.get_agent(organization_id, agent_id)
        if agent.status != VoiceAgentStatus.LIVE:
            raise ConflictError("Only a live agent can be paused.")
        agent.status = VoiceAgentStatus.PAUSED
        return agent

    async def resume(self, organization_id: str, agent_id: str) -> VoiceAgent:
        agent = await self.get_agent(organization_id, agent_id)
        if agent.status != VoiceAgentStatus.PAUSED:
            raise ConflictError("Only a paused agent can be resumed.")
        active = await self.get_active_version(organization_id, agent_id)
        if active is None:
            raise ConflictError("No published version to resume with.")
        agent.status = VoiceAgentStatus.LIVE
        return agent

    async def _get_editable_version(self, organization_id: str, agent_id: str) -> AgentVersion:
        for status in (AgentVersionStatus.APPROVED, AgentVersionStatus.TEST):
            version = await self._find_version_in_status(organization_id, agent_id, status)
            if version is not None:
                return version
        raise NotFoundError("No version in TEST or APPROVED state for this agent.")

    async def _require_version_in_status(
        self, organization_id: str, agent_id: str, status: AgentVersionStatus
    ) -> AgentVersion:
        version = await self._find_version_in_status(organization_id, agent_id, status)
        if version is None:
            raise NotFoundError(f"No version in {status.value.upper()} state for this agent.")
        return version

    async def _find_version_in_status(
        self, organization_id: str, agent_id: str, status: AgentVersionStatus
    ) -> AgentVersion | None:
        for version in await self.version_repo.list_for_agent(organization_id, agent_id):
            if version.status == status:
                return version
        return None

    async def _archive_current_active(self, organization_id: str, agent_id: str) -> None:
        current_active = await self.version_repo.get_active_published(organization_id, agent_id)
        if current_active is None:
            return
        current_active.is_active = False
        AGENT_VERSION_TRANSITIONS.assert_transition_allowed(
            current_active.status, AgentVersionStatus.ARCHIVED
        )
        current_active.status = AgentVersionStatus.ARCHIVED

    async def _open_new_draft(
        self, organization_id: str, agent: VoiceAgent, source: AgentVersion
    ) -> AgentVersion:
        next_number = (
            await self.version_repo.get_latest_version_number(organization_id, agent.id) + 1
        )
        return await self.version_repo.add(
            AgentVersion(
                organization_id=organization_id,
                voice_agent_id=agent.id,
                version_number=next_number,
                status=AgentVersionStatus.DRAFT,
                created_by_user_id=source.created_by_user_id,
                **_copy_config_sections(source),
            )
        )
