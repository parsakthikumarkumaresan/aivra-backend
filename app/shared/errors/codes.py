"""Stable, machine-readable error codes.

Frontend behavior depends on ``error.code``, never on message text
(spec section 27). Add new codes here rather than inlining strings at
call sites, so the full contract stays in one place.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    # --- Generic ---
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    IDEMPOTENCY_KEY_CONFLICT = "IDEMPOTENCY_KEY_CONFLICT"

    # --- Auth ---
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"

    # --- Authorization / tenancy ---
    FORBIDDEN = "FORBIDDEN"
    ORGANIZATION_MISMATCH = "ORGANIZATION_MISMATCH"
    MEMBERSHIP_REQUIRED = "MEMBERSHIP_REQUIRED"
    ROLE_NOT_PERMITTED = "ROLE_NOT_PERMITTED"

    # --- Employee entitlement ---
    EMPLOYEE_ACCESS_DENIED = "EMPLOYEE_ACCESS_DENIED"
    EMPLOYEE_NOT_PROVISIONED = "EMPLOYEE_NOT_PROVISIONED"
    SUBSCRIPTION_INACTIVE = "SUBSCRIPTION_INACTIVE"

    # --- Voice internal/customer split ---
    INTERNAL_VOICE_ACCESS_DENIED = "INTERNAL_VOICE_ACCESS_DENIED"

    # --- State machines ---
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"

    # --- Billing / webhooks ---
    WEBHOOK_SIGNATURE_INVALID = "WEBHOOK_SIGNATURE_INVALID"
    PAYMENT_FAILED = "PAYMENT_FAILED"
