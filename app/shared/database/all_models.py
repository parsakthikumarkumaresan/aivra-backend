"""Imports every ORM model across all bounded contexts so
``Base.metadata`` is fully populated for Alembic autogenerate and test
``create_all`` fixtures. Add new model modules here as they're created —
this is the one place allowed to "see" every context at once, since it
contains no logic, just imports.
"""

from __future__ import annotations

from app.ai_employees.hr.models.assessment import Assessment  # noqa: F401
from app.ai_employees.hr.models.candidate import Candidate, CandidateIdentity  # noqa: F401
from app.ai_employees.hr.models.integration import CalendarIntegration  # noqa: F401
from app.ai_employees.hr.models.interview import Interview  # noqa: F401
from app.ai_employees.hr.models.job import HrJob  # noqa: F401
from app.ai_employees.hr.models.processing_job import ProcessingJob  # noqa: F401
from app.ai_employees.hr.models.resume import Resume  # noqa: F401
from app.ai_employees.hr.models.schedule_slot import ScheduleSlot  # noqa: F401
from app.ai_employees.hr.models.screening import Screening  # noqa: F401
from app.ai_employees.provisioning.models.provision import (  # noqa: F401
    EmployeeProvision,
    ProvisioningEvent,
)
from app.ai_employees.registry.models.catalog import (  # noqa: F401
    AIEmployeeType,
    EmployeeCatalogItem,
)
from app.ai_employees.voice.models.agent_version import AgentVersion  # noqa: F401
from app.ai_employees.voice.models.call import Call  # noqa: F401
from app.ai_employees.voice.models.call_analysis import CallAnalysis  # noqa: F401
from app.ai_employees.voice.models.call_event import CallEvent  # noqa: F401
from app.ai_employees.voice.models.call_usage import CallUsage  # noqa: F401
from app.ai_employees.voice.models.compliance import ComplianceRecord, DndEntry  # noqa: F401
from app.ai_employees.voice.models.phone_number import PhoneNumber  # noqa: F401
from app.ai_employees.voice.models.recording import Recording  # noqa: F401
from app.ai_employees.voice.models.routing_rule import RoutingRule  # noqa: F401
from app.ai_employees.voice.models.sip_trunk import SipTrunk  # noqa: F401
from app.ai_employees.voice.models.telephony_provider import TelephonyProviderAccount  # noqa: F401
from app.ai_employees.voice.models.tool import Tool  # noqa: F401
from app.ai_employees.voice.models.tool_execution import ToolExecution  # noqa: F401
from app.ai_employees.voice.models.transcript import Transcript  # noqa: F401
from app.ai_employees.voice.models.voice_agent import VoiceAgent  # noqa: F401
from app.audit.models.audit_event import AuditEvent  # noqa: F401
from app.billing.models.invoice import Invoice  # noqa: F401
from app.billing.models.payment_event import PaymentEvent  # noqa: F401
from app.identity.models.session import RefreshToken, Session  # noqa: F401
from app.identity.models.user import User  # noqa: F401
from app.knowledge.models.document_chunk import DocumentChunk  # noqa: F401
from app.knowledge.models.source import KnowledgeCollection, KnowledgeSource  # noqa: F401
from app.knowledge.models.source_version import SourceVersion  # noqa: F401
from app.leads.models.lead import Lead  # noqa: F401
from app.leads.models.requirement import Requirement  # noqa: F401
from app.leads.models.voice_project import VoiceProject  # noqa: F401
from app.organizations.models.membership import OrganizationMember  # noqa: F401
from app.organizations.models.organization import Organization  # noqa: F401
from app.shared.database.base import Base
from app.subscriptions.models.plan import Plan  # noqa: F401
from app.subscriptions.models.subscription import Subscription  # noqa: F401

__all__ = ["Base"]
