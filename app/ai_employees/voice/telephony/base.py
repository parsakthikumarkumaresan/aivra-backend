from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ProvisionedNumberResult:
    provider_number_id: str
    number: str
    country: str
    monthly_cost: float
    currency: str


@dataclass(frozen=True)
class OriginatedCallResult:
    provider_call_id: str
    status: str


class TelephonyProvider(ABC):
    @abstractmethod
    async def provision_phone_number(
        self, country: str, area_code: str | None = None
    ) -> ProvisionedNumberResult:
        """Provision a phone number from the carrier/provider."""

    @abstractmethod
    async def release_phone_number(self, provider_number_id: str) -> None:
        """Release a provisioned phone number back to the carrier."""

    @abstractmethod
    async def originate_call(
        self, from_number: str, to_number: str, room_name: str
    ) -> OriginatedCallResult:
        """Originate an outbound call bridging into a LiveKit room."""
