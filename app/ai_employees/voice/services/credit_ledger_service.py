from __future__ import annotations

from datetime import datetime

from app.ai_employees.voice.models.credit_transaction import (
    CreditTransaction,
    CreditTransactionType,
)
from app.ai_employees.voice.repositories.credit_ledger_repository import CreditLedgerRepository
from app.ai_employees.voice.services.billing import compute_billable_minutes
from app.shared.errors.exceptions import InsufficientCreditsError


class CreditLedgerService:
    """Jaan Voice Credit ledger — organization-scoped, additive-only
    transaction log (Phase 4 spec sections 1, 9). Balance is always derived
    (``SUM(minutes)``); nothing here ever stores or trusts a mutable
    "remaining minutes" field.
    """

    def __init__(self, ledger_repo: CreditLedgerRepository) -> None:
        self.ledger_repo = ledger_repo

    async def get_balance(self, organization_id: str) -> int:
        return await self.ledger_repo.get_balance(organization_id)

    async def get_summary(
        self, organization_id: str, *, low_balance_threshold_minutes: int
    ) -> dict[str, int | bool | datetime | None]:
        balance = await self.ledger_repo.get_balance(organization_id)
        totals = await self.ledger_repo.get_totals(organization_id)
        last_recharge_at = await self.ledger_repo.get_last_recharge_at(organization_id)
        return {
            "balance_minutes": balance,
            "purchased_minutes": totals["purchased"],
            "used_minutes": totals["used"],
            "low_balance": balance < low_balance_threshold_minutes,
            "last_recharge_at": last_recharge_at,
        }

    async def list_transactions(
        self, organization_id: str, *, limit: int = 100
    ) -> list[CreditTransaction]:
        return await self.ledger_repo.list_for_organization(organization_id, limit=limit)

    async def assert_can_start_call(self, organization_id: str, *, minimum_balance: int) -> None:
        """Call admission gate (spec section 6). Only gates whether a NEW
        call may start — an already-admitted call is never interrupted for
        running out of credit mid-call.
        """
        balance = await self.ledger_repo.get_balance_for_update(organization_id)
        if balance < minimum_balance:
            raise InsufficientCreditsError(
                f"Insufficient Jaan Voice Credits: {balance} minute(s) remaining, "
                f"at least {minimum_balance} required to start a call."
            )

    async def debit_for_call(
        self, organization_id: str, call_id: str, *, duration_seconds: int
    ) -> CreditTransaction | None:
        """Idempotent post-call usage debit (spec sections 5, 13). Safe to
        call more than once for the same call_id — from a retried RQ job or
        a re-delivered LiveKit webhook — because:

        1. An existence check short-circuits before taking any lock.
        2. The re-check after acquiring the org's advisory lock closes the
           race window between two concurrent finalizations of the same
           call.
        3. ``credit_transactions.call_id`` has a DB-level unique
           constraint as a final backstop even if both prior guards were
           somehow bypassed.

        Returns None (no debit) for a call that never actually connected
        (duration_seconds == 0) — see ``compute_billable_minutes``.
        """
        existing = await self.ledger_repo.get_usage_debit_by_call_id(organization_id, call_id)
        if existing is not None:
            return existing

        billable_minutes = compute_billable_minutes(duration_seconds)
        if billable_minutes == 0:
            return None

        await self.ledger_repo.lock_organization_ledger(organization_id)
        existing = await self.ledger_repo.get_usage_debit_by_call_id(organization_id, call_id)
        if existing is not None:
            return existing

        transaction = CreditTransaction(
            organization_id=organization_id,
            type=CreditTransactionType.USAGE_DEBIT,
            minutes=-billable_minutes,
            call_id=call_id,
            reason=(
                f"Voice call {call_id} ({duration_seconds}s, "
                f"{billable_minutes} billable minute(s))"
            ),
        )
        return await self.ledger_repo.add(transaction)

    async def grant(
        self,
        organization_id: str,
        *,
        type: CreditTransactionType,
        minutes: int,
        reason: str | None = None,
        reference: str | None = None,
        amount: float | None = None,
        currency: str | None = None,
        recharge_order_id: str | None = None,
        created_by_user_id: str | None = None,
    ) -> CreditTransaction:
        """Generic ledger-write path for every non-usage transaction type:
        recharge confirmation, complimentary/initial allocation, admin
        adjustment, refund. Every manual (admin-initiated) grant must pass
        ``created_by_user_id`` and a human-readable ``reason`` — enforced
        at the API layer (AdminAddCreditsRequest), not here, so this method
        stays reusable for system-initiated grants (e.g. the recharge
        webhook) too.
        """
        await self.ledger_repo.lock_organization_ledger(organization_id)
        transaction = CreditTransaction(
            organization_id=organization_id,
            type=type,
            minutes=minutes,
            amount=amount,
            currency=currency,
            reference=reference,
            reason=reason,
            recharge_order_id=recharge_order_id,
            created_by_user_id=created_by_user_id,
        )
        return await self.ledger_repo.add(transaction)
