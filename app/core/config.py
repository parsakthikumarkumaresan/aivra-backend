"""Typed application configuration loaded from environment variables.

Single source of truth for runtime configuration. Nothing outside this module
should call `os.environ` directly — see spec section 34 (Configuration
Management) and section 35 (secrets never live in source code).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---
    app_env: AppEnv = AppEnv.LOCAL
    app_name: str = "aivra-backend"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    # --- HTTP / CORS ---
    # Comma-separated in the environment (pydantic-settings tries to JSON-decode
    # list-typed fields before validators run, which breaks plain CSV env vars) —
    # stored raw and split via the `cors_allow_origins` property below.
    cors_allow_origins_raw: str = Field(default="", alias="CORS_ALLOW_ORIGINS")
    request_id_header: str = "X-Request-ID"

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://aivra:aivra@localhost:5432/aivra"
    )
    database_pool_size: int = 10
    database_max_overflow: int = 10
    database_echo: bool = False

    # --- Redis / queue ---
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- Auth / sessions ---
    jwt_secret_key: SecretStr = Field(default=SecretStr("insecure-dev-secret-change-me"))
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "aivra-backend"
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 30 * 24 * 60 * 60
    refresh_cookie_name: str = "aivra_refresh"
    csrf_cookie_name: str = "aivra_csrf"
    password_reset_ttl_seconds: int = 60 * 60
    login_max_attempts: int = 5
    login_lockout_seconds: int = 15 * 60

    # --- Object storage (S3-compatible) ---
    object_storage_endpoint_url: str | None = None
    object_storage_region: str = "us-east-1"
    object_storage_bucket_documents: str = "aivra-documents"
    object_storage_bucket_recordings: str = "aivra-recordings"
    object_storage_access_key_id: SecretStr = Field(default=SecretStr(""))
    object_storage_secret_access_key: SecretStr = Field(default=SecretStr(""))
    object_storage_signed_url_ttl_seconds: int = 5 * 60

    # --- AI providers ---
    # ADR 0002: OpenAI is the LLM vendor for BOTH AI Employees. Vendor
    # selection is centralized here (app.shared.ai_providers.factory); model
    # choice is intentionally NOT centralized — each employee has its own
    # model setting below so changing one can never affect the other.
    llm_provider: str = "openai"
    openai_api_key: SecretStr = Field(default=SecretStr(""))
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # HR-scoped LLM configuration (extraction/matching/scoring — spec 9.3).
    hr_llm_model: str = "gpt-4o-mini"

    # Voice-scoped LLM configuration (conversational runtime — spec 11) and
    # a separate model for non-realtime Voice tasks (post-call analysis,
    # spec 15) which doesn't need the realtime API.
    voice_llm_model: str = "gpt-4o-mini"
    voice_realtime_model: str = "gpt-4o-realtime-preview"

    # --- STT / TTS (Voice-scoped; consumed only by the Voice runtime) ---
    stt_provider: str = "deepgram"
    deepgram_api_key: SecretStr = Field(default=SecretStr(""))
    tts_provider: str = "cartesia"
    cartesia_api_key: SecretStr = Field(default=SecretStr(""))

    # --- Voice real-time runtime (ADR 0002: LiveKit) ---
    livekit_url: str = ""
    livekit_api_key: SecretStr = Field(default=SecretStr(""))
    livekit_api_secret: SecretStr = Field(default=SecretStr(""))

    # --- HR AI voice screening runtime (LiveKit + SIP) — independently
    # scoped from Voice's livekit_*/voice_* settings above (spec: HR/Voice
    # bounded-context isolation). Same physical LiveKit/SIP account may be
    # reused; the settings fields themselves must never be shared, so a
    # future change to Voice's configuration can never affect HR screening.
    hr_livekit_url: str = ""
    hr_livekit_api_key: SecretStr = Field(default=SecretStr(""))
    hr_livekit_api_secret: SecretStr = Field(default=SecretStr(""))
    hr_sip_trunk_id: str = ""
    hr_screening_phone_number: str = ""
    hr_screening_agent_name: str = "aivra-hr-screening"
    # HR-configurable AI persona/display name spoken on calls — never
    # hardcoded (spec section 8).
    hr_screening_persona_name: str = "Aivra Hr"
    hr_screening_realtime_model: str = "gpt-realtime"
    hr_screening_voice: str = "marin"

    # --- Telephony ---
    telephony_provider: str = "twilio"
    twilio_account_sid: SecretStr = Field(default=SecretStr(""))
    twilio_auth_token: SecretStr = Field(default=SecretStr(""))
    twilio_webhook_signing_secret: SecretStr = Field(default=SecretStr(""))

    # --- Payments ---
    # Stripe chosen as the MVP payment provider (ADR: docs/adr/0001-payment-provider.md) —
    # its checkout/subscription/invoice/billing-portal/webhook model matches the
    # spec's representative API surface (GET /billing/portal, invoices, webhooks)
    # far more directly than a transaction-only gateway.
    payment_provider: str = "stripe"
    stripe_secret_key: SecretStr = Field(default=SecretStr(""))
    stripe_webhook_secret: SecretStr = Field(default=SecretStr(""))
    stripe_api_base_url: str = "https://api.stripe.com/v1"
    billing_portal_return_url: str = "http://localhost:5173/app/settings/billing"
    checkout_success_url: str = "http://localhost:5173/app/employees?checkout=success"
    checkout_cancel_url: str = "http://localhost:5173/app/employees?checkout=cancelled"

    # --- Calendar ---
    calendar_provider: str = "google"
    google_calendar_client_id: str = ""
    google_calendar_client_secret: SecretStr = Field(default=SecretStr(""))

    # --- Email / SMS ---
    email_provider: str = "smtp"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = Field(default=SecretStr(""))
    email_from_address: str = "noreply@aivra.ai"
    sms_provider: str = "twilio"

    # --- Observability ---
    otel_exporter_endpoint: str | None = None
    sentry_dsn: str | None = None

    @property
    def cors_allow_origins(self) -> list[str]:
        origins = self.cors_allow_origins_raw.split(",")
        return [origin.strip() for origin in origins if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == AppEnv.PRODUCTION

    @property
    def is_local(self) -> bool:
        return self.app_env in (AppEnv.LOCAL, AppEnv.TEST)


@lru_cache
def get_settings() -> Settings:
    return Settings()
