"""Calendar provider abstraction (spec sections 21, 29). HR-owned — Voice
has no calendar dependency, so this lives under HR, not shared platform.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CalendarEvent:
    event_id: str
    meeting_link: str | None


class CalendarProvider(ABC):
    @abstractmethod
    async def create_event(
        self,
        *,
        access_token: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        attendee_emails: list[str],
    ) -> CalendarEvent: ...
