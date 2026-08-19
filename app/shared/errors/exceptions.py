"""Application exception hierarchy.

Raise these from services/repositories; ``app.shared.errors.handlers``
converts them into the stable error envelope at the API boundary.
"""

from __future__ import annotations

from app.shared.errors.codes import ErrorCode


class AppError(Exception):
    status_code: int = 400
    code: ErrorCode = ErrorCode.VALIDATION_ERROR

    def __init__(
        self, message: str, *, code: ErrorCode | None = None, details: dict | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = ErrorCode.NOT_FOUND


class ConflictError(AppError):
    status_code = 409
    code = ErrorCode.CONFLICT


class ValidationAppError(AppError):
    status_code = 422
    code = ErrorCode.VALIDATION_ERROR


class AuthenticationRequiredError(AppError):
    status_code = 401
    code = ErrorCode.AUTHENTICATION_REQUIRED


class InvalidCredentialsError(AppError):
    status_code = 401
    code = ErrorCode.INVALID_CREDENTIALS


class AccountLockedError(AppError):
    status_code = 423
    code = ErrorCode.ACCOUNT_LOCKED


class TokenInvalidError(AppError):
    status_code = 401
    code = ErrorCode.TOKEN_INVALID


class TokenExpiredError(AppError):
    status_code = 401
    code = ErrorCode.TOKEN_EXPIRED


class ForbiddenError(AppError):
    status_code = 403
    code = ErrorCode.FORBIDDEN


class RoleNotPermittedError(AppError):
    status_code = 403
    code = ErrorCode.ROLE_NOT_PERMITTED


class MembershipRequiredError(AppError):
    status_code = 403
    code = ErrorCode.MEMBERSHIP_REQUIRED


class EmployeeAccessDeniedError(AppError):
    status_code = 403
    code = ErrorCode.EMPLOYEE_ACCESS_DENIED


class SubscriptionInactiveError(AppError):
    status_code = 403
    code = ErrorCode.SUBSCRIPTION_INACTIVE


class InternalVoiceAccessDeniedError(AppError):
    status_code = 403
    code = ErrorCode.INTERNAL_VOICE_ACCESS_DENIED


class InvalidStateTransitionError(AppError):
    status_code = 409
    code = ErrorCode.INVALID_STATE_TRANSITION


class RateLimitedError(AppError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED


class IdempotencyKeyConflictError(AppError):
    status_code = 409
    code = ErrorCode.IDEMPOTENCY_KEY_CONFLICT


class WebhookSignatureInvalidError(AppError):
    status_code = 400
    code = ErrorCode.WEBHOOK_SIGNATURE_INVALID
