from __future__ import annotations

from enum import StrEnum

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base, OrgScopedMixin
from app.shared.database.ids import IdPrefix, new_id
from app.shared.database.types import str_enum_column


class CreditTransactionType(StrEnum):
    INITIAL_ALLOCATION = "initial_allocation"
    USAGE_DEBIT = "usage_debit"
    RECHARGE = "recharge"
    COMPLIMENTARY = "complimentary"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    REFUND = "refund"


class CreditTransaction(Base, OrgScopedMixin):
    """Jaan Voice Credit ledger — the sole source of truth for an
    organization's voice-minute balance (Phase 4 spec section 1).

    There is deliberately no mutable ``remaining_minutes`` anywhere:
    balance is always ``SUM(minutes)`` over this table
    (CreditLedgerRepository.get_balance), computed inside a row-locking
    transaction wherever it gates a mutation (recharge apply, usage debit,
    admin adjustment) to make concurrent debits/credits safe.

    ``minutes`` is signed: positive for credits (RECHARGE, COMPLIMENTARY,
    INITIAL_ALLOCATION, a positive ADMIN_ADJUSTMENT/REFUND), negative for
    USAGE_DEBIT. This table is Jaan-Voice-specific and intentionally lives
    in the voice module, not a shared/platform billing table — HR usage
    must never read or write it.
    """

    __tablename__ = "voice_credit_transactions"
    __table_args__ = (
        # Defense-in-depth alongside the application-level idempotency
        # check in CreditLedgerService.debit_for_call: at most one
        # USAGE_DEBIT row can ever exist per call, even under concurrent
        # post-call-analysis job retries (Postgres treats multiple NULLs in
        # a unique index as distinct, so this only constrains rows that
        # actually set call_id).
        UniqueConstraint("call_id", name="uq_voice_credit_txn_call_id"),
    )

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: new_id(IdPrefix.CREDIT_TRANSACTION)
    )
    type: Mapped[CreditTransactionType] = mapped_column(
        str_enum_column(CreditTransactionType, 30), nullable=False
    )
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Money actually paid/refunded for this transaction (RECHARGE/REFUND) —
    # null for USAGE_DEBIT and non-monetary adjustments. Never derived from
    # or exposed alongside internal provider cost (see CallUsage), which
    # customers never see.
    amount: Mapped[float | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    reference: Mapped[str | None] = mapped_column(String(255))
    recharge_order_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("voice_recharge_orders.id", ondelete="SET NULL"), index=True
    )
    call_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("calls.id", ondelete="SET NULL")
    )
    reason: Mapped[str | None] = mapped_column(Text)
    # Null for system-generated transactions (usage debits, webhook-driven
    # recharge confirmations) — set to the acting user's ID only for
    # admin-initiated adjustments, so every manual credit change is
    # attributable (spec section 8/13 audit requirement).
    created_by_user_id: Mapped[str | None] = mapped_column(String(40))
