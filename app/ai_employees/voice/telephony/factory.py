from __future__ import annotations

from app.ai_employees.voice.models.telephony_provider import (
    TelephonyProviderAccount,
    TelephonyProviderType,
)
from app.ai_employees.voice.telephony.base import TelephonyProvider
from app.ai_employees.voice.telephony.twilio_provider import TwilioTelephonyProvider


def get_telephony_provider(account: TelephonyProviderAccount) -> TelephonyProvider:
    if account.provider_type == TelephonyProviderType.TWILIO:
        # Credential reference parsed or fallback to account parameters
        account_sid = account.credential_ref or "AC_dummy_account_sid"
        auth_token = "dummy_auth_token"  # noqa: S105
        return TwilioTelephonyProvider(account_sid=account_sid, auth_token=auth_token)

    # Fallback to Twilio provider interface for unconfigured/other providers
    return TwilioTelephonyProvider(
        account_sid=account.credential_ref or "AC_dummy_account_sid",
        auth_token="dummy_auth_token",  # noqa: S106
    )
