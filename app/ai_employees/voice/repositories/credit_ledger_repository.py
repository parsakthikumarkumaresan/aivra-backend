from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, text

from app.ai_employees.voice.models.credit_transaction import (
    CreditTransaction,
    CreditTransactionType,
)
from app.shared.database.repository import OrgScopedRepository


class CreditLedgerRepository(OrgScopedRepository[CreditTransaction]):
    model = CreditTransaction

    async def lock_organization_ledger(self, organization_id: str) -> None:
        """Takes a Postgres transaction-scoped advisory lock keyed by
        organization_id (Phase 4 spec section 13: concurrent debits/credits
        for the same org must serialize, e.g. two calls ending at once must
        never both read the same stale balance).

        Uses ``pg_advisory_xact_lock`` rather than ``SELECT ... FOR UPDATE``
        because it works even when the organization has zero ledger rows
        yet (its very first transaction) — a row lock can't protect rows
        that don't exist. The lock is released automatically at
        commit/rollback of the current transaction; callers must acquire it
        before reading the balance they intend to act on, inside the same
        DB transaction as the write that follows.
        """
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:org_id)::bigint)"),
            {"org_id": organization_id},
        )

    async def get_balance_for_update(self, organization_id: str) -> int:
        """Locks the organization's ledger, then returns its current
        balance. See ``lock_organization_ledger``.
        """
        await self.lock_organization_ledger(organization_id)
        return await self.get_balance(organization_id)

    async def get_balance(self, organization_id: str) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(CreditTransaction.minutes), 0)).where(
                CreditTransaction.organization_id == organization_id
            )
        )
        return int(result.scalar_one())

    async def get_totals(self, organization_id: str) -> dict[str, int]:
        """Purchased vs. used minutes for the admin customer-detail view
        (spec section 12) — purchased = every positive transaction, used =
        the magnitude of USAGE_DEBIT transactions.
        """
        result = await self.session.execute(
            select(
                func.coalesce(
                    func.sum(CreditTransaction.minutes).filter(CreditTransaction.minutes > 0), 0
                ),
                func.coalesce(
                    func.sum(-CreditTransaction.minutes).filter(
                        CreditTransaction.type == CreditTransactionType.USAGE_DEBIT
                    ),
                    0,
                ),
            ).where(CreditTransaction.organization_id == organization_id)
        )
        purchased, used = result.one()
        return {"purchased": int(purchased), "used": int(used)}

    async def get_last_recharge_at(self, organization_id: str) -> datetime | None:
        result = await self.session.execute(
            select(func.max(CreditTransaction.created_at)).where(
                CreditTransaction.organization_id == organization_id,
                CreditTransaction.type == CreditTransactionType.RECHARGE,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_organization(
        self, organization_id: str, *, limit: int = 100
    ) -> list[CreditTransaction]:
        result = await self.session.execute(
            select(CreditTransaction)
            .where(CreditTransaction.organization_id == organization_id)
            .order_by(CreditTransaction.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_usage_debit_by_call_id(
        self, organization_id: str, call_id: str
    ) -> CreditTransaction | None:
        result = await self.session.execute(
            select(CreditTransaction).where(
                CreditTransaction.organization_id == organization_id,
                CreditTransaction.call_id == call_id,
                CreditTransaction.type == CreditTransactionType.USAGE_DEBIT,
            )
        )
        return result.scalar_one_or_none()

    async def get_recharge_by_order_id(
        self, organization_id: str, recharge_order_id: str
    ) -> CreditTransaction | None:
        result = await self.session.execute(
            select(CreditTransaction).where(
                CreditTransaction.organization_id == organization_id,
                CreditTransaction.recharge_order_id == recharge_order_id,
                CreditTransaction.type == CreditTransactionType.RECHARGE,
            )
        )
        return result.scalar_one_or_none()
