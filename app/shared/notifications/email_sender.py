"""Email sending abstraction. Platform-level (not HR-scoped) since email is
generically reusable infra — same reasoning as the shared LLM/OCR/calendar
adapter pattern (ADR 0002-style: one adapter, no per-employee duplication).
HR's interview invitations are the first consumer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmailSender(ABC):
    @abstractmethod
    async def send(self, *, to: list[str], subject: str, body: str) -> None: ...
