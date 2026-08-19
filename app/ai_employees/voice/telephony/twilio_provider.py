from __future__ import annotations

import httpx

from app.ai_employees.voice.telephony.base import (
    OriginatedCallResult,
    ProvisionedNumberResult,
    TelephonyProvider,
)
from app.shared.errors.exceptions import AppError


class TwilioTelephonyProvider(TelephonyProvider):
    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self._http_client = http_client
        self.base_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"

    async def provision_phone_number(
        self, country: str, area_code: str | None = None
    ) -> ProvisionedNumberResult:
        client_provided = self._http_client is not None
        client = self._http_client or httpx.AsyncClient()
        try:
            url = f"{self.base_url}/IncomingPhoneNumbers.json"
            data = {"IsoCountry": country.upper()}
            if area_code:
                data["AreaCode"] = area_code

            response = await client.post(
                url, data=data, auth=(self.account_sid, self.auth_token)
            )
            if response.status_code >= 400:
                raise AppError(f"Twilio provision number failed: {response.text}")

            result = response.json()
            return ProvisionedNumberResult(
                provider_number_id=result.get("sid", "PN_mock"),
                number=result.get("phone_number", "+15550199"),
                country=country.upper(),
                monthly_cost=1.15,
                currency="USD",
            )
        finally:
            if not client_provided:
                await client.aclose()

    async def release_phone_number(self, provider_number_id: str) -> None:
        client_provided = self._http_client is not None
        client = self._http_client or httpx.AsyncClient()
        try:
            url = f"{self.base_url}/IncomingPhoneNumbers/{provider_number_id}.json"
            response = await client.delete(url, auth=(self.account_sid, self.auth_token))
            if response.status_code >= 400 and response.status_code != 404:
                raise AppError(f"Twilio release number failed: {response.text}")
        finally:
            if not client_provided:
                await client.aclose()

    async def originate_call(
        self, from_number: str, to_number: str, room_name: str
    ) -> OriginatedCallResult:
        client_provided = self._http_client is not None
        client = self._http_client or httpx.AsyncClient()
        try:
            url = f"{self.base_url}/Calls.json"
            data = {
                "From": from_number,
                "To": to_number,
                "Url": f"https://api.aivra.ai/v1/internal/voice/telephony/sip-twiml?room={room_name}",
            }
            response = await client.post(
                url, data=data, auth=(self.account_sid, self.auth_token)
            )
            if response.status_code >= 400:
                raise AppError(f"Twilio call origination failed: {response.text}")

            result = response.json()
            return OriginatedCallResult(
                provider_call_id=result.get("sid", "CA_mock"),
                status=result.get("status", "queued"),
            )
        finally:
            if not client_provided:
                await client.aclose()
