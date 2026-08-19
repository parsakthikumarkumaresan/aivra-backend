# ADR 0003: Voice bounded context — knowledge placement and versioning reconciliation

**Status:** Accepted

## Context

Spec section 52 requires documenting conflicts between the specification, the
existing backend, and the existing frontend rather than silently picking one.
Two conflicts surfaced while designing the Voice bounded context.

## Decision 1: Knowledge/RAG is shared-platform, not Voice-owned

The frontend's `KnowledgeSource` type (`src/types/knowledge.ts`) carries
`employeeAccess: EmployeeType[]` — a single source can be scoped to `'hr'`,
`'voice'`, or both. This is a real, load-bearing part of the existing UI
(access-control checkboxes per employee), not an accident. Spec section 12
("Knowledge/RAG") is also presented as its own numbered section, structurally
parallel to section 9 (HR) and sections 10–11 (Voice), not nested under
either.

Building Knowledge under `app.ai_employees.voice` would force a choice
between (a) breaking the frontend's cross-employee access control, or (b)
having HR import Voice's knowledge module — the latter directly violates the
non-negotiable HR/Voice isolation rule.

**Decision**: Knowledge/RAG lives under `app/knowledge/` as shared-platform
infrastructure (peer to `app.shared.storage`, `app.audit`), organization-
scoped with an `employee_access` field gating retrieval per employee type.
Voice's `AgentVersion.library` config section stores `knowledge_source_ids`
(references into this shared table), never a Voice-owned copy. HR may adopt
the same references later without any Voice import. This is consistent with
spec's reference architecture (section 46), which places
"PostgreSQL + pgvector" at the shared platform tier, not inside Voice.

## Decision 2: Draft mutation vs. immutable publish/rollback

The frontend's `voiceAgentBuilderService.updateVoiceAgent(id, patch)` shallow-
merges a config-section patch and bumps a single `version: number` +
`lastUpdatedAt` on every edit — i.e. the prototype treats "version" as an
edit counter, not spec's immutable published-version history.

Spec section 20 is explicit and non-negotiable here: "Published
configurations are immutable... every call references the exact published
configuration version... Rollback → activate previous version." Silently
adopting the frontend's simpler model would break auditability of what
configuration actually handled a given call — unacceptable for a domain
with compliance/consent requirements (spec section 24).

**Decision**: Follow the spec's real versioning model —
`AgentVersion` rows are immutable once `PUBLISHED`; a `DRAFT` version is
mutable in place. The frontend's PATCH contract is satisfied by editing the
current `DRAFT` version's config sections in place (this *is* a real,
correct implementation of "edit the draft," not a compatibility shim) and
returning its running revision count as `version` on the `VoiceAgent`
response the frontend already expects. Publishing creates a new immutable
version; rollback creates a new version copying an older one's config
(append-only history — matches spec's "Version 1 (archived) / Version 2
(archived) / Version 3 (ACTIVE)" diagram exactly).

## Consequences

- HR/Voice isolation is preserved and, if anything, strengthened — neither
  context owns Knowledge, so there is no import path between them through it.
- `GET/PATCH` VoiceAgent endpoints operate on the draft version under the
  hood; a separate `POST /publish` and `POST /rollback` implement the real
  spec lifecycle. No frontend change is required for basic editing; the
  publish/rollback/test-approval endpoints are additive.
- Every `Call` row stores the exact `agent_version_id` that handled it,
  satisfying the Definition of Done requirement directly.
