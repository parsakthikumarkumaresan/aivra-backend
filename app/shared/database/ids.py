"""Prefixed, sortable identifiers (Stripe/Linear-style), e.g. ``org_01jc8...``.

Backed by ULID (26-char, lexicographically sortable by creation time) so
primary keys double as a stable creation-order index without a separate
``created_at`` sort in hot paths. Spec section 18 allows UUID or ULID; the
audit-log examples in section 38 (``org_...``, ``user_...``, ``agent_...``)
use prefixed opaque IDs, so we standardize on that shape everywhere.
"""

from __future__ import annotations

from ulid import ULID


def new_id(prefix: str) -> str:
    return f"{prefix}_{ULID()!s}".lower()


# Canonical prefixes — keep in sync with the model that owns each one.
class IdPrefix:
    USER = "user"
    SESSION = "ses"
    REFRESH_TOKEN = "rtok"
    ORGANIZATION = "org"
    MEMBERSHIP = "mem"
    ROLE = "role"
    AI_EMPLOYEE_TYPE = "aet"
    CATALOG_ITEM = "cat"
    EMPLOYEE_PROVISION = "prov"
    PROVISIONING_EVENT = "provevt"
    PLAN = "plan"
    SUBSCRIPTION = "sub"
    INVOICE = "inv"
    PAYMENT_EVENT = "payevt"
    LEAD = "lead"
    VOICE_PROJECT = "vproj"
    REQUIREMENT = "req"
    APPROVAL = "appr"
    NOTIFICATION = "notif"
    AUDIT_EVENT = "audit"
    HR_JOB = "job"
    CANDIDATE = "cand"
    RESUME = "resume"
    PROCESSING_JOB = "pjob"
    ASSESSMENT = "assess"
    SCREENING = "screen"
    INTERVIEW = "interview"
    SCHEDULE_SLOT = "slot"
    VOICE_AGENT = "vagent"
    AGENT_VERSION = "aver"
    PROMPT = "prompt"
    FLOW = "flow"
    CONTEXT = "ctx"
    TOOL = "tool"
    TOOL_VERSION = "toolver"
    TOOL_EXECUTION = "toolexec"
    KNOWLEDGE_COLLECTION = "kcol"
    KNOWLEDGE_SOURCE = "ksrc"
    SOURCE_VERSION = "ksrcver"
    DOCUMENT_CHUNK = "chunk"
    CALL = "call"
    CALL_EVENT = "callevt"
    TRANSCRIPT = "transcript"
    RECORDING = "rec"
    CALL_ANALYSIS = "callan"
    TELEPHONY_PROVIDER = "telprov"
    PHONE_NUMBER = "phone"
    SIP_TRUNK = "sip"
    ROUTE = "route"
    COMPLIANCE_RECORD = "comp"
    DND_ENTRY = "dnd"
    INTEGRATION = "integ"
    IDEMPOTENCY_KEY = "idem"
    CALL_USAGE = "calluse"
