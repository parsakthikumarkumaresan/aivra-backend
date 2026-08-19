# ADR 0002: LLM provider and Voice real-time runtime

**Status:** Accepted — explicit project decision (overrides default MVP judgment calls)

## Context

Spec section 44 requires freezing LLM/STT/TTS providers before deep AI
integration work. The project owner has now given explicit, binding
instructions for both.

## Decision

1. **LLM vendor: OpenAI for both AI HR Employee and AI Voice Employee.**
   No Gemini/Bedrock/other vendor as the primary implementation unless
   explicitly instructed otherwise.
2. **Voice real-time runtime: LiveKit.** Telephony/SIP/WebRTC connects into
   LiveKit; LiveKit hosts the real-time agent session (STT/VAD → agent
   runtime → LLM → TTS). This sits at the runtime/infrastructure layer, not
   inside Voice domain logic (spec section 11: runtime scales independently
   from the control plane).
3. **Per-employee configuration isolation.** HR and Voice must never share
   a mutable AI configuration object. Concretely:
   - The OpenAI *adapter* (`app.shared.ai_providers.openai_llm_provider.OpenAILLMProvider`)
     is shared infrastructure — one implementation, no duplication.
   - The OpenAI *model choice* is NOT shared: `settings.hr_llm_model` and
     `settings.voice_llm_model` / `settings.voice_realtime_model` are
     separate config fields. HR code calls
     `app.ai_employees.hr.ai.provider.get_hr_llm_provider()`; Voice will
     call an equivalent `app.ai_employees.voice.runtime.llm_provider.get_voice_llm_provider()`
     when the Voice bounded context is built. Neither module imports the
     other's scoped factory.
   - STT/TTS/LiveKit credentials are consumed only by the Voice runtime
     layer — HR has no code path that can read or depend on them.
   - Prompts, flows, knowledge, and tool configuration are separate DB
     tables per bounded context (HR: `assessments`, etc.; Voice: to be
     built under `app.ai_employees.voice.*`) — there is no single global
     "AI config" row either employee writes to.

## Consequences

- Swapping HR's or Voice's model (or, later, vendor) only touches that
  employee's scoped factory module and its own settings fields — never the
  other employee's code or config, and never the shared adapter.
- LiveKit integration lives behind a Voice-runtime-owned interface once
  built (analogous to `PaymentProvider`/`TelephonyProvider`); LiveKit SDK
  calls do not appear in Voice domain entities/services.
- No LiveKit or OpenAI credentials are configured in this environment.
  Adapters are implemented against the real documented API shape but are
  untested against live accounts — same posture as ADR 0001 (spec section
  47: no fake completion).
